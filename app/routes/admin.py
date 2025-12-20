from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.routes.user import _is_admin

router = APIRouter()


def _admin_dir() -> Path:
    preferred = Path("/data") / "autonomy-labs" / "admin"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        fallback = Path.home() / ".autonomy-labs" / "admin"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _templates_path() -> Path:
    return _admin_dir() / "mcp-templates.json"


def _require_admin(user: dict[str, Any]) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")


class McpTemplates(BaseModel):
    version: int = 1
    templates: list[dict[str, Any]] = []


@router.get("/api/admin/mcp-templates")
async def get_mcp_templates(http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    path = _templates_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "templates": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/api/admin/mcp-templates")
async def put_mcp_templates(body: McpTemplates, http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)

    # Light validation: ensure each template has id + url.
    templates = []
    for t in body.templates or []:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id") or t.get("name") or "").strip()
        url = str(t.get("url") or "").strip()
        if not tid or not url:
            continue
        templates.append(t)

    payload = {"version": int(body.version or 1), "templates": templates}
    path = _templates_path()
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"ok": True, "count": len(templates)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
