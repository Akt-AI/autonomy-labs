from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.mcp_client import McpStdioClient
from app.routes.base import router as base_router
from app.routes.chat import router as chat_router
from app.routes.codex import router as codex_router
from app.routes.mcp import router as mcp_router
from app.routes.terminal import router as terminal_router
from app.routes.user import router as user_router

_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.codex_mcp_client = McpStdioClient(["codex", "mcp-server"])
    app.state.device_login_attempts = {}
    app.state.device_login_lock = asyncio.Lock()
    stop = asyncio.Event()

    async def _cleanup_device_logins():
        # Best-effort pruning to keep memory bounded.
        while not stop.is_set():
            await asyncio.sleep(60)
            try:
                now = asyncio.get_running_loop().time()
                attempts = getattr(app.state, "device_login_attempts", {})
                for key, attempt in list(attempts.items()):
                    created = getattr(attempt, "created_at", 0.0) or 0.0
                    age = now - created
                    done = bool(getattr(attempt, "done", False))
                    # Keep active attempts for up to 30 minutes; completed for 5 minutes.
                    if age > 1800 or (done and age > 300):
                        attempts.pop(key, None)
            except Exception:
                continue

    cleanup_task = asyncio.create_task(_cleanup_device_logins())
    try:
        yield
    finally:
        stop.set()
        cleanup_task.cancel()
        try:
            await app.state.codex_mcp_client.close()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = _ROOT / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(base_router)
    app.include_router(chat_router)
    app.include_router(codex_router)
    app.include_router(mcp_router)
    app.include_router(terminal_router)
    app.include_router(user_router)

    return app
