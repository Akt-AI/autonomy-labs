from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "static"


@router.get("/config")
async def get_config():
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", "https://znhglkwefxdhgajvrqmb.supabase.co"),
        "supabase_key": os.environ.get("SUPABASE_KEY"),
        "default_base_url": os.environ.get("DEFAULT_BASE_URL", "https://router.huggingface.co/v1"),
        "default_api_key": os.environ.get("DEFAULT_API_KEY", ""),
        "default_model": os.environ.get("DEFAULT_MODEL", "gpt-3.5-turbo"),
    }


@router.get("/")
async def read_index():
    return FileResponse(str(_STATIC / "landing.html"))


@router.get("/login")
async def read_login():
    return FileResponse(str(_STATIC / "index.html"))


@router.get("/app")
async def read_app():
    return FileResponse(str(_STATIC / "dashboard.html"))


@router.get("/settings")
async def read_settings():
    # Dedicated route: render the main app, but have the UI auto-open Settings for deep links.
    return FileResponse(str(_STATIC / "dashboard.html"))


@router.get("/admin")
async def read_admin():
    # Dedicated route: render the main app, but have the UI auto-open Admin for deep links.
    return FileResponse(str(_STATIC / "dashboard.html"))


@router.get("/health")
async def health_check():
    return {"status": "ok"}
