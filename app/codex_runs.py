from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CodexRun:
    id: str
    user_id: str
    created_at: float
    proc: asyncio.subprocess.Process
    args: list[str]
    # Ring buffer of NDJSON lines (without trailing newline).
    _offset: int = 0
    _lines: list[str] = field(default_factory=list)
    done: bool = False
    returncode: int | None = None
    thread_id: str | None = None
    final_text: str = ""
    usage: dict[str, Any] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    updated: asyncio.Condition = field(default_factory=asyncio.Condition)

    def start_cursor(self) -> int:
        return self._offset

    def end_cursor(self) -> int:
        return self._offset + len(self._lines)

    async def append_line(self, line: str) -> None:
        text = (line or "").rstrip("\n")
        if not text:
            return
        async with self.lock:
            self._lines.append(text)
            # Keep up to ~2500 events; drop older and advance offset.
            if len(self._lines) > 2500:
                drop = len(self._lines) - 2500
                self._lines = self._lines[drop:]
                self._offset += drop
        async with self.updated:
            self.updated.notify_all()

    async def append_event(self, event: dict[str, Any]) -> None:
        await self.append_line(json.dumps(event, ensure_ascii=False))

    async def snapshot_from(self, cursor: int) -> tuple[int, list[str]]:
        async with self.lock:
            start = self._offset
            end = self._offset + len(self._lines)
            cur = max(int(cursor), 0)
            if cur < start:
                cur = start
            if cur > end:
                cur = end
            idx = cur - start
            return cur, list(self._lines[idx:])

    async def wait_for_new(self, cursor: int, timeout: float = 25.0) -> None:
        cur = max(int(cursor), 0)
        async with self.updated:
            try:
                await asyncio.wait_for(self._wait_predicate(cur), timeout=timeout)
            except TimeoutError:
                return

    async def _wait_predicate(self, cursor: int) -> None:
        while True:
            if self.done:
                return
            if self.end_cursor() > cursor:
                return
            await self.updated.wait()


class CodexRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, CodexRun] = {}
        self._lock = asyncio.Lock()

    async def create_run(self, *, user_id: str, args: list[str], env: dict[str, str]) -> CodexRun:
        run_id = str(uuid.uuid4())
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        run = CodexRun(
            id=run_id,
            user_id=user_id,
            created_at=asyncio.get_running_loop().time(),
            proc=proc,
            args=args,
        )
        async with self._lock:
            self._runs[run_id] = run
        asyncio.create_task(self._pump(run))
        return run

    async def get_run(self, run_id: str) -> CodexRun | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def cancel_run(self, run_id: str, *, user_id: str) -> bool:
        run = await self.get_run(run_id)
        if not run or run.user_id != user_id:
            return False
        if run.done:
            return True
        try:
            run.proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(run.proc.wait(), timeout=3)
        except Exception:
            try:
                run.proc.kill()
            except ProcessLookupError:
                pass
        return True

    async def prune(self) -> None:
        now = asyncio.get_running_loop().time()
        async with self._lock:
            for rid, run in list(self._runs.items()):
                age = now - (run.created_at or now)
                # Keep running runs up to 1 hour; completed up to 10 minutes.
                if run.done and age > 600:
                    self._runs.pop(rid, None)
                elif not run.done and age > 3600:
                    self._runs.pop(rid, None)

    async def _pump(self, run: CodexRun) -> None:
        assert run.proc.stdout is not None
        assert run.proc.stderr is not None

        try:
            while True:
                line_b = await run.proc.stdout.readline()
                if not line_b:
                    break
                raw = line_b.decode("utf-8", errors="ignore").strip()
                if not raw:
                    continue
                try:
                    evt = json.loads(raw)
                except Exception:
                    await run.append_event({"type": "log", "message": raw})
                    continue

                t = evt.get("type")
                if t == "thread.started":
                    run.thread_id = evt.get("thread_id") or run.thread_id
                elif t == "item.completed":
                    item = evt.get("item") or {}
                    if item.get("type") == "agent_message":
                        run.final_text = item.get("text") or run.final_text
                elif t == "turn.completed":
                    run.usage = evt.get("usage") or run.usage

                await run.append_line(raw)
        except Exception as e:
            await run.append_event({"type": "stderr", "message": str(e)})
        finally:
            try:
                await run.proc.wait()
            except Exception:
                pass
            run.returncode = run.proc.returncode
            run.done = True
            try:
                err_text = (await run.proc.stderr.read()).decode("utf-8", errors="ignore").strip()
            except Exception:
                err_text = ""
            if run.returncode and err_text:
                await run.append_event({"type": "stderr", "message": err_text, "returnCode": run.returncode})
            await run.append_event(
                {
                    "type": "done",
                    "runId": run.id,
                    "threadId": run.thread_id,
                    "finalResponse": run.final_text,
                    "usage": run.usage,
                    "returnCode": run.returncode,
                }
            )
