from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.codex_runs import CodexRunStore
from app.errors import normalize_error
from app.indexing_jobs import IndexJobStore
from app.mcp_client import McpStdioClient
from app.rooms_store import RoomsStore
from app.routes.admin import router as admin_router
from app.routes.base import router as base_router
from app.routes.chat import router as chat_router
from app.routes.codex import router as codex_router
from app.routes.indexing import router as indexing_router
from app.routes.mcp import router as mcp_router
from app.routes.rooms import router as rooms_router
from app.routes.rag import router as rag_router
from app.routes.terminal import router as terminal_router
from app.routes.user import router as user_router
from app.routes.vault import router as vault_router

_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.codex_mcp_client = McpStdioClient(["codex", "mcp-server"])
    app.state.codex_run_store = CodexRunStore()
    app.state.index_job_store = IndexJobStore()
    app.state.rooms_store = RoomsStore()
    app.state.rooms_connections = {}
    app.state.rooms_lock = asyncio.Lock()
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

    async def _cleanup_codex_runs():
        while not stop.is_set():
            await asyncio.sleep(60)
            try:
                await app.state.codex_run_store.prune()
            except Exception:
                continue

    cleanup_task = asyncio.create_task(_cleanup_device_logins())
    cleanup_runs_task = asyncio.create_task(_cleanup_codex_runs())
    try:
        yield
    finally:
        stop.set()
        cleanup_task.cancel()
        cleanup_runs_task.cancel()
        try:
            await app.state.codex_mcp_client.close()
        except Exception:
            pass


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(_request, exc: StarletteHTTPException):
        err = normalize_error(exc.detail, status_code=exc.status_code)
        # Keep `detail` for backward compatibility with existing UI; add structured `error`.
        return JSONResponse(status_code=exc.status_code, content={"detail": err["message"], "error": err})

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(_request, exc: RequestValidationError):
        err = normalize_error(exc.errors(), status_code=422, default_code="validation_error")
        return JSONResponse(status_code=422, content={"detail": err["message"], "error": err})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request, exc: Exception):
        err = normalize_error(str(exc), status_code=500, default_code="internal_error")
        return JSONResponse(status_code=500, content={"detail": err["message"], "error": err})

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
    app.include_router(indexing_router)
    app.include_router(mcp_router)
    app.include_router(terminal_router)
    app.include_router(rooms_router)
    app.include_router(user_router)
    app.include_router(admin_router)
    app.include_router(rag_router)
    app.include_router(vault_router)

    return app
