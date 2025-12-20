from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import HTTPException


class McpStdioClient:
    def __init__(self, command: list[str]):
        self.command = command
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._reader_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def start(self) -> None:
        if self.proc and self.proc.returncode is None:
            return
        self.proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._initialized = False
        self._reader_task = asyncio.create_task(self._reader())
        await self._initialize()

    async def close(self) -> None:
        if not self.proc:
            return
        try:
            if self.proc.returncode is None:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=5.0)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        finally:
            self.proc = None
            self._initialized = False
            if self._reader_task:
                self._reader_task.cancel()
                self._reader_task = None

    async def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except Exception:
                continue
            msg_id = msg.get("id")
            if msg_id is None:
                continue
            fut = self._pending.pop(int(msg_id), None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def _rpc(self, method: str, params: Optional[dict] = None) -> dict:
        await self.start()
        assert self.proc and self.proc.stdin
        async with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[msg_id] = fut
            payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
            if params is not None:
                payload["params"] = params
            self.proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()
        resp = await asyncio.wait_for(fut, timeout=600.0)
        if "error" in resp:
            raise HTTPException(status_code=500, detail=resp["error"])
        return resp.get("result") or {}

    async def _initialize(self) -> None:
        if self._initialized:
            return
        _ = await self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "autonomy-labs", "version": "1.0"},
                "capabilities": {},
            },
        )
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode("utf-8")
        )
        await self.proc.stdin.drain()
        self._initialized = True

    async def list_tools(self) -> dict:
        return await self._rpc("tools/list", {})

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

