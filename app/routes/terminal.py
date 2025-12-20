from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import struct
import subprocess
import termios
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, WebSocket

from app.auth import verify_supabase_access_token
from app.settings import feature_enabled

router = APIRouter()


@router.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()

    if not feature_enabled("terminal"):
        await websocket.send_text("\r\n[terminal disabled]\r\n")
        await websocket.close()
        return

    # Browser WebSocket APIs do not allow setting Authorization headers directly.
    token = (websocket.query_params.get("token") or "").strip()
    if not token:
        await websocket.send_text("\r\n[unauthorized: missing token]\r\n")
        await websocket.close()
        return
    try:
        _user = await verify_supabase_access_token(token)
    except HTTPException as e:
        await websocket.send_text(f"\r\n[unauthorized: {e.detail}]\r\n")
        await websocket.close()
        return

    # If token-based Codex auth is provided via env (HF Spaces Secrets), ensure the CLI auth file exists.
    try:
        id_token = os.environ.get("CODEX_ID_TOKEN") or os.environ.get("ID_TOKEN") or ""
        access_token = os.environ.get("CODEX_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
        refresh_token = os.environ.get("CODEX_REFRESH_TOKEN") or os.environ.get("REFRESH_TOKEN") or ""
        account_id = os.environ.get("CODEX_ACCOUNT_ID") or os.environ.get("ACCOUNT_ID") or ""
        if id_token or access_token or refresh_token:
            codex_home = os.path.join(os.path.expanduser("~"), ".codex")
            os.makedirs(codex_home, exist_ok=True)
            auth = {
                "OPENAI_API_KEY": None,
                "tokens": {
                    "id_token": id_token,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "account_id": account_id,
                },
                "last_refresh": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for filename in ("auth.json", ".auth.json"):
                path = os.path.join(codex_home, filename)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(auth, f, indent=2)
                    f.write("\n")
                try:
                    os.chmod(path, 0o600)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as e:
        await websocket.send_text(
            "\r\n[terminal unavailable: PTY allocation failed]\r\n" f"{type(e).__name__}: {e}\r\n"
        )
        await websocket.close()
        return

    env = os.environ.copy()
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("COLORTERM", "truecolor")
    p = subprocess.Popen(
        ["/bin/bash", "-i"],
        preexec_fn=os.setsid,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
    )

    os.close(slave_fd)
    loop = asyncio.get_running_loop()

    async def read_from_pty():
        while True:
            try:
                data = await loop.run_in_executor(None, lambda: os.read(master_fd, 1024))
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
            except Exception:
                break
        await websocket.close()

    async def write_to_pty():
        try:
            while True:
                data = await websocket.receive_text()
                if data.startswith("\x01resize:"):
                    try:
                        _, cols, rows = data.split(":")
                        cols_i = int(cols)
                        rows_i = int(rows)
                        if cols_i < 2 or rows_i < 2:
                            continue
                        winsize = struct.pack("HHHH", rows_i, cols_i, 0, 0)
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                    except Exception:
                        pass
                else:
                    os.write(master_fd, data.encode())
        except Exception:
            pass

    read_task = asyncio.create_task(read_from_pty())
    write_task = asyncio.create_task(write_to_pty())

    try:
        await asyncio.wait([read_task, write_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        read_task.cancel()
        write_task.cancel()
        p.terminate()
        os.close(master_fd)
