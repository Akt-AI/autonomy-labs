from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.settings import feature_enabled
from app.storage import user_data_dir

router = APIRouter()


def _is_admin(user: dict[str, Any]) -> bool:
    # Minimal heuristic; can be replaced with Supabase custom claims / RLS-backed roles later.
    meta = user.get("user_metadata") or {}
    if isinstance(meta, dict) and meta.get("is_admin") is True:
        return True
    email = str(user.get("email") or "").strip().lower()
    user_id = str(user.get("id") or "").strip()

    admin_emails = {e.strip().lower() for e in (os.environ.get("ADMIN_EMAILS") or "").split(",") if e.strip()}
    admin_ids = {e.strip() for e in (os.environ.get("ADMIN_USER_IDS") or "").split(",") if e.strip()}
    if email and email in admin_emails:
        return True
    if user_id and user_id in admin_ids:
        return True
    return False


@router.get("/api/me")
async def me(http_request: Request):
    user = await require_user_from_request(http_request)
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "isAdmin": _is_admin(user),
        "features": {
            "terminal": feature_enabled("terminal"),
            "codex": feature_enabled("codex"),
            "mcp": feature_enabled("mcp"),
            "indexing": feature_enabled("indexing"),
        },
    }


class McpRegistry(BaseModel):
    version: int = 1
    servers: list[dict[str, Any]] = []


def _registry_path(user_id: str) -> str:
    return str(user_data_dir(user_id) / "mcp-registry.json")


@router.get("/api/user/mcp-registry")
async def get_mcp_registry(http_request: Request):
    user = await require_user_from_request(http_request)
    path = _registry_path(str(user.get("id") or ""))
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"version": 1, "servers": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


@router.put("/api/user/mcp-registry")
async def put_mcp_registry(body: McpRegistry, http_request: Request):
    user = await require_user_from_request(http_request)
    path = _registry_path(str(user.get("id") or ""))

    # Light validation: ensure each server has an id and url.
    servers = []
    for s in body.servers or []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or s.get("name") or "").strip()
        url = str(s.get("url") or "").strip()
        if not sid or not url:
            continue
        servers.append(s)

    payload = {"version": int(body.version or 1), "servers": servers}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return {"ok": True, "count": len(servers)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e
