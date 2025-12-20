from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.settings import feature_enabled
from app.storage import user_data_dir

router = APIRouter()


def _rag_dir(user_id: str) -> Path:
    root = user_data_dir(user_id) / "rag"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path(user_id: str) -> Path:
    return _rag_dir(user_id) / "rag-index.json"


@dataclass(frozen=True)
class _Chunk:
    id: str
    text: str


def _chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[_Chunk]:
    t = (text or "").strip()
    if not t:
        return []
    chunks: list[_Chunk] = []
    i = 0
    n = len(t)
    while i < n:
        j = min(n, i + max_chars)
        chunk = t[i:j].strip()
        if chunk:
            chunks.append(_Chunk(id=str(uuid.uuid4()), text=chunk))
        if j >= n:
            break
        i = max(0, j - overlap)
    return chunks


def _load_index(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "documents": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _save_index(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/api/rag/documents")
async def list_documents(http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail="Indexing is disabled")
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    idx_path = _index_path(user_id)
    idx = _load_index(idx_path)
    docs = idx.get("documents") if isinstance(idx.get("documents"), list) else []
    out = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        out.append(
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "createdAt": d.get("createdAt"),
                "bytes": d.get("bytes"),
                "chunks": len(d.get("chunks") or []),
            }
        )
    return {"documents": out}


@router.post("/api/rag/documents/upload")
async def upload_document(file: UploadFile, http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail="Indexing is disabled")
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    name = (file.filename or "document").strip()
    if len(name) > 200:
        name = name[:200]

    try:
        text = data.decode("utf-8")
    except Exception:
        try:
            text = data.decode("latin-1")
        except Exception as e:
            raise HTTPException(status_code=400, detail="Unsupported encoding") from e

    doc_id = str(uuid.uuid4())
    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No indexable text found")

    rag_root = _rag_dir(user_id)
    doc_path = rag_root / f"{doc_id}.txt"
    doc_path.write_text(text, encoding="utf-8")

    idx_path = _index_path(user_id)
    idx = _load_index(idx_path)
    docs = idx.get("documents")
    if not isinstance(docs, list):
        docs = []
        idx["documents"] = docs

    docs.append(
        {
            "id": doc_id,
            "name": name,
            "createdAt": _now_iso(),
            "bytes": len(data),
            "path": doc_path.name,
            "chunks": [{"id": c.id, "text": c.text} for c in chunks],
        }
    )
    _save_index(idx_path, idx)
    return {"ok": True, "id": doc_id, "chunks": len(chunks)}


@router.delete("/api/rag/documents/{doc_id}")
async def delete_document(doc_id: str, http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail="Indexing is disabled")
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")

    idx_path = _index_path(user_id)
    idx = _load_index(idx_path)
    docs = idx.get("documents")
    if not isinstance(docs, list):
        docs = []
        idx["documents"] = docs

    before = len(docs)
    kept = []
    removed = None
    for d in docs:
        if isinstance(d, dict) and str(d.get("id") or "") == doc_id:
            removed = d
        else:
            kept.append(d)
    idx["documents"] = kept
    _save_index(idx_path, idx)

    if removed is not None:
        try:
            path = removed.get("path")
            if isinstance(path, str) and path:
                (_rag_dir(user_id) / path).unlink(missing_ok=True)
        except Exception:
            pass

    return {"ok": True, "deleted": 1 if removed is not None else 0, "before": before, "after": len(kept)}


class SearchRequest(BaseModel):
    query: str
    limit: int = 8


@router.post("/api/rag/search")
async def search(request: SearchRequest, http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail="Indexing is disabled")
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")

    q = (request.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing query")

    idx_path = _index_path(user_id)
    idx = _load_index(idx_path)
    docs = idx.get("documents") if isinstance(idx.get("documents"), list) else []

    terms = [t for t in re.split(r"\\W+", q.lower()) if t]
    if not terms:
        raise HTTPException(status_code=400, detail="Invalid query")

    results = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        doc_name = str(d.get("name") or "")
        doc_id = str(d.get("id") or "")
        chunks = d.get("chunks") if isinstance(d.get("chunks"), list) else []
        for ch in chunks:
            if not isinstance(ch, dict):
                continue
            text = str(ch.get("text") or "")
            hay = text.lower()
            score = sum(hay.count(t) for t in terms)
            if score <= 0:
                continue
            first = None
            for t in terms:
                pos = hay.find(t)
                if pos != -1:
                    first = pos
                    break
            if first is None:
                first = 0
            start = max(0, first - 120)
            end = min(len(text), first + 240)
            excerpt = text[start:end].strip()
            results.append(
                {
                    "score": score,
                    "document": {"id": doc_id, "name": doc_name},
                    "chunkId": ch.get("id"),
                    "excerpt": excerpt,
                }
            )

    results.sort(key=lambda r: int(r.get("score") or 0), reverse=True)
    limit = max(1, min(int(request.limit or 8), 25))
    return {"results": results[:limit]}

