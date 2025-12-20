from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.feature_overrides import load_feature_overrides, save_feature_overrides
from app.routes.user import _is_admin
from app.settings import feature_enabled


def _admin_supabase_config() -> tuple[str, str]:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE")
    if not supabase_url or not service_key:
        raise HTTPException(
            status_code=503,
            detail={"code": "supabase_admin_not_configured", "message": "Missing SUPABASE_SERVICE_ROLE_KEY"},
        )
    return supabase_url.rstrip("/"), service_key


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None



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
        raise HTTPException(status_code=403, detail={"code": "admin_required", "message": "Admin privileges required"})


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
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


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
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


class FeatureOverridesBody(BaseModel):
    overrides: dict[str, bool]


@router.get("/api/admin/features")
async def get_feature_overrides(http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    overrides = load_feature_overrides()
    features = ["terminal", "codex", "mcp", "indexing", "rooms", "vault"]
    return {
        "ok": True,
        "features": {
            f: {"enabled": feature_enabled(f), "override": overrides.get(f)}
            for f in features
        },
        "overrides": overrides,
    }


@router.put("/api/admin/features")
async def put_feature_overrides(body: FeatureOverridesBody, http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    allowed = {"terminal", "codex", "mcp", "indexing", "rooms", "vault"}
    overrides = {}
    for k, v in (body.overrides or {}).items():
        key = str(k).strip()
        if key in allowed and isinstance(v, bool):
            overrides[key] = v
    saved = save_feature_overrides(overrides)
    return {"ok": True, "overrides": saved}


class UsersPruneBody(BaseModel):
    olderThanDays: int = 90
    inactiveOnly: bool = True
    maxDelete: int = 50


@router.get("/api/admin/users")
async def list_users(http_request: Request, page: int = 1, perPage: int = 50):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    base_url, service_key = _admin_supabase_config()

    import httpx

    params = {"page": max(1, int(page)), "per_page": max(1, min(int(perPage), 200))}
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    url = f"{base_url}/auth/v1/admin/users"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail={"code": "supabase_admin_error", "message": resp.text[:4000]},
            )
        data = resp.json()
        users = data.get("users") if isinstance(data, dict) else None
        return {"users": users or [], "page": params["page"], "perPage": params["per_page"]}


@router.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: str, http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    if str(user_id).strip() == str(user.get("id") or "").strip():
        raise HTTPException(
            status_code=400,
            detail={"code": "cannot_delete_self", "message": "Cannot delete the current user"},
        )
    base_url, service_key = _admin_supabase_config()

    import httpx

    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    url = f"{base_url}/auth/v1/admin/users/{user_id}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(url, headers=headers)
        if resp.status_code not in {200, 204}:
            raise HTTPException(
                status_code=resp.status_code,
                detail={"code": "supabase_admin_error", "message": resp.text[:4000]},
            )
        return {"ok": True, "deleted": True}


@router.post("/api/admin/users/prune")
async def prune_users(body: UsersPruneBody, http_request: Request):
    user = await require_user_from_request(http_request)
    _require_admin(user)
    base_url, service_key = _admin_supabase_config()

    import httpx

    cutoff_days = max(1, int(body.olderThanDays or 90))
    max_delete = max(1, min(int(body.maxDelete or 50), 200))
    inactive_only = bool(body.inactiveOnly)

    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    url = f"{base_url}/auth/v1/admin/users"
    params = {"page": 1, "per_page": 200}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail={"code": "supabase_admin_error", "message": resp.text[:4000]},
            )
        data = resp.json()
        users = data.get("users") if isinstance(data, dict) else []

        now = datetime.now(timezone.utc)
        deleted = []
        for u in users:
            if len(deleted) >= max_delete:
                break
            if not isinstance(u, dict):
                continue
            uid = str(u.get("id") or "").strip()
            if not uid or uid == str(user.get("id") or ""):
                continue
            created_at = _parse_iso(u.get("created_at"))
            last_sign_in = _parse_iso(u.get("last_sign_in_at"))
            if inactive_only and last_sign_in:
                age_days = (now - last_sign_in).days
            else:
                age_days = (now - created_at).days if created_at else 0
            if age_days < cutoff_days:
                continue
            del_resp = await client.delete(f"{base_url}/auth/v1/admin/users/{uid}", headers=headers)
            if del_resp.status_code in {200, 204}:
                deleted.append(uid)
        return {"ok": True, "deleted": deleted, "count": len(deleted)}
