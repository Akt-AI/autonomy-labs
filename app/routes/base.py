from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_ROOT = Path(__file__).resolve().parents[2]
_STATIC = _ROOT / "static"
_DOCS_ROOT = _ROOT / "docs"

_DOC_PAGES: dict[str, tuple[str, Path]] = {
    "architecture": ("Architecture", _DOCS_ROOT / "ARCHITECTURE.md"),
    "troubleshooting": ("Troubleshooting", _DOCS_ROOT / "TROUBLESHOOTING.md"),
    "security-deployment": ("Security deployment", _DOCS_ROOT / "SECURITY_DEPLOYMENT.md"),
    "password-manager-scope": ("Password manager scope", _DOCS_ROOT / "PASSWORD_MANAGER_SCOPE.md"),
}


def _config_payload() -> dict:
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", "https://znhglkwefxdhgajvrqmb.supabase.co"),
        "supabase_key": os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY"),
        "default_base_url": os.environ.get("DEFAULT_BASE_URL", "https://router.huggingface.co/v1"),
        "default_api_key": os.environ.get("DEFAULT_API_KEY", ""),
        "default_model": os.environ.get("DEFAULT_MODEL", "gpt-3.5-turbo"),
    }


@router.get("/config")
async def get_config():
    return _config_payload()


@router.get("/api/config")
async def get_api_config():
    return _config_payload()


@router.get("/api/app-docs")
async def list_app_docs():
    return {
        "pages": [
            {"slug": slug, "title": title}
            for slug, (title, _path) in sorted(_DOC_PAGES.items(), key=lambda kv: kv[1][0].lower())
        ]
    }


@router.get("/api/app-docs/{slug}")
async def get_app_doc(slug: str):
    entry = _DOC_PAGES.get(slug)
    if not entry:
        raise HTTPException(status_code=404, detail="Doc not found")
    title, path = entry
    try:
        markdown = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Doc not found") from e
    return {"slug": slug, "title": title, "markdown": markdown}


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


@router.get("/docs")
async def read_docs():
    return FileResponse(str(_STATIC / "docs.html"))


@router.get("/health")
async def health_check():
    return {"status": "ok"}
