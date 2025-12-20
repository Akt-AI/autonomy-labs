from __future__ import annotations

import asyncio
import json
import re
import socket
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException

from app.storage import user_data_dir


def _jobs_path(user_id: str) -> Path:
    return user_data_dir(user_id) / "indexing-jobs.json"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_public_host(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception:
        return False

    import ipaddress

    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except Exception:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Missing URL"})
    p = urlparse(u)
    if p.scheme not in {"https", "http"}:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "URL must be http(s)"})
    if not p.netloc:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "URL must include a host"})
    if not _is_public_host(p.hostname or ""):
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Host is not allowed"})
    # Normalize: strip fragment, keep query.
    normalized = p._replace(fragment="").geturl()
    return normalized


def _extract_links(html: str) -> list[str]:
    # Best-effort: handle common href patterns; ignore javascript:, mailto:, etc.
    out: list[str] = []
    for m in re.finditer(r"""href\s*=\s*['"]([^'"]+)['"]""", html, flags=re.IGNORECASE):
        href = (m.group(1) or "").strip()
        if not href:
            continue
        if href.startswith("#"):
            continue
        if href.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
            continue
        out.append(href)
    return out


def _html_to_text(html: str) -> str:
    s = html or ""
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p\s*>", "\n\n", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[dict[str, str]]:
    t = (text or "").strip()
    if not t:
        return []
    chunks: list[dict[str, str]] = []
    i = 0
    n = len(t)
    while i < n:
        j = min(n, i + max_chars)
        chunk = t[i:j].strip()
        if chunk:
            chunks.append({"id": str(uuid.uuid4()), "text": chunk})
        if j >= n:
            break
        i = max(0, j - overlap)
    return chunks


def _rag_dir(user_id: str) -> Path:
    root = user_data_dir(user_id) / "rag"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _rag_index_path(user_id: str) -> Path:
    return _rag_dir(user_id) / "rag-index.json"


def _load_rag_index(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "documents": []}


def _save_rag_index(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_rag_document(user_id: str, *, name: str, text: str, source: str | None = None) -> dict[str, Any]:
    doc_id = str(uuid.uuid4())
    chunks = _chunk_text(text)
    rag_root = _rag_dir(user_id)
    doc_path = rag_root / f"{doc_id}.txt"
    doc_path.write_text(text, encoding="utf-8")

    idx_path = _rag_index_path(user_id)
    idx = _load_rag_index(idx_path)
    docs = idx.get("documents")
    if not isinstance(docs, list):
        docs = []
        idx["documents"] = docs

    entry: dict[str, Any] = {
        "id": doc_id,
        "name": name,
        "createdAt": _now_iso(),
        "bytes": len(text.encode("utf-8")),
        "path": doc_path.name,
        "chunks": chunks,
    }
    if source:
        entry["source"] = source

    docs.append(entry)
    _save_rag_index(idx_path, idx)
    return {"id": doc_id, "chunks": len(chunks)}


@dataclass
class IndexJob:
    id: str
    type: str
    createdAt: str
    status: str = "queued"  # queued|running|succeeded|failed|canceled
    params: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class IndexJobStore:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, dict[str, asyncio.Task]] = {}

    def _lock(self, user_id: str) -> asyncio.Lock:
        if user_id not in self._locks:
            self._locks[user_id] = asyncio.Lock()
        return self._locks[user_id]

    def _task_map(self, user_id: str) -> dict[str, asyncio.Task]:
        return self._tasks.setdefault(user_id, {})

    async def list_jobs(self, user_id: str) -> list[dict[str, Any]]:
        path = _jobs_path(user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(jobs, list):
                return []
            return [j for j in jobs if isinstance(j, dict)]
        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            return []

    async def get_job(self, user_id: str, job_id: str) -> dict[str, Any] | None:
        for j in await self.list_jobs(user_id):
            if str(j.get("id") or "") == job_id:
                return j
        return None

    async def _save_jobs(self, user_id: str, jobs: list[dict[str, Any]]) -> None:
        path = _jobs_path(user_id)
        payload = {"version": 1, "jobs": jobs}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    async def _update_job(self, user_id: str, job: IndexJob) -> None:
        async with self._lock(user_id):
            jobs = await self.list_jobs(user_id)
            updated = False
            for i, j in enumerate(jobs):
                if str(j.get("id") or "") == job.id:
                    jobs[i] = asdict(job)
                    updated = True
                    break
            if not updated:
                jobs.append(asdict(job))
            await self._save_jobs(user_id, jobs)

    async def cancel_job(self, user_id: str, job_id: str) -> bool:
        task = self._task_map(user_id).get(job_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def create_web_crawl_job(
        self,
        user_id: str,
        *,
        start_url: str,
        max_pages: int = 25,
        max_depth: int = 2,
        rate_limit_sec: float = 0.25,
        respect_robots: bool = True,
    ) -> IndexJob:
        url = _normalize_url(start_url)
        max_pages = max(1, min(int(max_pages), 150))
        max_depth = max(0, min(int(max_depth), 6))
        rate_limit_sec = float(rate_limit_sec)
        if rate_limit_sec < 0:
            rate_limit_sec = 0.0
        if rate_limit_sec > 5:
            rate_limit_sec = 5.0

        job = IndexJob(
            id=str(uuid.uuid4()),
            type="web_crawl",
            createdAt=_now_iso(),
            params={
                "startUrl": url,
                "maxPages": max_pages,
                "maxDepth": max_depth,
                "rateLimitSec": rate_limit_sec,
                "respectRobots": bool(respect_robots),
            },
        )
        await self._update_job(user_id, job)

        task = asyncio.create_task(self._run_web_crawl(user_id, job))
        self._task_map(user_id)[job.id] = task
        return job

    async def _run_web_crawl(self, user_id: str, job: IndexJob) -> None:
        job.status = "running"
        job.progress = {"visited": 0, "indexedPages": 0, "queued": 0}
        await self._update_job(user_id, job)

        start_url = job.params.get("startUrl") or ""
        max_pages = int(job.params.get("maxPages") or 25)
        max_depth = int(job.params.get("maxDepth") or 2)
        rate_limit_sec = float(job.params.get("rateLimitSec") or 0.25)
        respect_robots = bool(job.params.get("respectRobots") is True)

        origin = urlparse(start_url)
        allowed_netloc = origin.netloc
        base = f"{origin.scheme}://{origin.netloc}"

        robots_disallow_all = False
        if respect_robots:
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=False, headers={"User-Agent": "autonomy-labs/1.0"}) as c:
                    r = await c.get(f"{base}/robots.txt")
                if r.status_code == 200:
                    txt = (r.text or "")
                    # Very small parser: disallow all if user-agent * has Disallow: /
                    in_star = False
                    for line in txt.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.lower().startswith("user-agent:"):
                            ua = line.split(":", 1)[1].strip()
                            in_star = ua == "*"
                        if in_star and line.lower().startswith("disallow:"):
                            val = line.split(":", 1)[1].strip()
                            if val == "/":
                                robots_disallow_all = True
                                break
            except Exception:
                robots_disallow_all = False

        if robots_disallow_all:
            job.status = "failed"
            job.error = "robots.txt disallows crawling"
            await self._update_job(user_id, job)
            return

        queue: list[tuple[str, int]] = [(start_url, 0)]
        visited: set[str] = set()
        pages: list[tuple[str, str]] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, headers={"User-Agent": "autonomy-labs/1.0"}) as client:
            try:
                while queue and len(visited) < max_pages:
                    url, depth = queue.pop(0)
                    if url in visited:
                        continue
                    visited.add(url)
                    job.progress = {"visited": len(visited), "indexedPages": len(pages), "queued": len(queue)}
                    await self._update_job(user_id, job)

                    parsed = urlparse(url)
                    if parsed.scheme not in {"https", "http"}:
                        continue
                    if parsed.netloc != allowed_netloc:
                        continue
                    if not _is_public_host(parsed.hostname or ""):
                        continue

                    resp = await client.get(url)
                    if resp.status_code in {301, 302, 303, 307, 308}:
                        loc = resp.headers.get("location") or ""
                        if loc:
                            nxt = urljoin(url, loc)
                            nxtp = urlparse(nxt)
                            if nxtp.netloc == allowed_netloc and nxt not in visited:
                                queue.append((nxt, depth))
                        await asyncio.sleep(rate_limit_sec)
                        continue
                    if resp.status_code != 200:
                        await asyncio.sleep(rate_limit_sec)
                        continue

                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "text/html" not in ctype:
                        await asyncio.sleep(rate_limit_sec)
                        continue
                    content = resp.text
                    if len(content) > 1_000_000:
                        content = content[:1_000_000]

                    text = _html_to_text(content)
                    if text:
                        pages.append((url, text))

                    if depth < max_depth:
                        for href in _extract_links(content):
                            nxt = urljoin(url, href)
                            try:
                                nxt = _normalize_url(nxt)
                            except HTTPException:
                                continue
                            nxtp = urlparse(nxt)
                            if nxtp.netloc != allowed_netloc:
                                continue
                            if nxt not in visited:
                                queue.append((nxt, depth + 1))

                    await asyncio.sleep(rate_limit_sec)
            except asyncio.CancelledError:
                job.status = "canceled"
                job.error = None
                await self._update_job(user_id, job)
                return
            except Exception as e:
                job.status = "failed"
                job.error = str(e)
                await self._update_job(user_id, job)
                return

        # Build a single RAG doc
        combined = []
        for url, text in pages:
            combined.append(f"URL: {url}\n\n{text}\n\n---\n")
        combined_text = "\n".join(combined).strip()
        if not combined_text:
            job.status = "failed"
            job.error = "No indexable pages found"
            await self._update_job(user_id, job)
            return

        result = add_rag_document(user_id, name=f"Website: {start_url}", text=combined_text, source=start_url)
        job.status = "succeeded"
        job.result = {"pages": len(pages), "ragDoc": result}
        job.progress = {"visited": len(visited), "indexedPages": len(pages), "queued": 0}
        await self._update_job(user_id, job)
