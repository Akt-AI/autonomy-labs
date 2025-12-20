from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request

_SUPABASE_TOKEN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


async def verify_supabase_access_token(access_token: str) -> dict[str, Any]:
    """
    Verifies a Supabase access token by calling Supabase Auth `GET /auth/v1/user`.
    Uses a small in-memory TTL cache to avoid calling Supabase on every request.
    """
    access_token = (access_token or "").strip()
    if not access_token:
        raise HTTPException(status_code=401, detail={"code": "missing_token", "message": "Missing access token"})

    now = time.time()
    cached = _SUPABASE_TOKEN_CACHE.get(access_token)
    if cached and (now - cached[0]) < 30:
        return cached[1]

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        raise HTTPException(
            status_code=503,
            detail={"code": "supabase_not_configured", "message": "Supabase is not configured"},
        )

    import httpx

    headers = {"Authorization": f"Bearer {access_token}", "apikey": supabase_key}
    url = f"{supabase_url.rstrip('/')}/auth/v1/user"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail={"code": "invalid_session", "message": "Invalid or expired session"})

        user = resp.json()
        _SUPABASE_TOKEN_CACHE[access_token] = (now, user)

        # Best-effort cache bound.
        if len(_SUPABASE_TOKEN_CACHE) > 500:
            for k in list(_SUPABASE_TOKEN_CACHE.keys())[:200]:
                _SUPABASE_TOKEN_CACHE.pop(k, None)
        return user


async def require_user_from_request(request: Request) -> dict[str, Any]:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"code": "missing_bearer_token", "message": "Missing Authorization bearer token"},
        )
    token = auth.split(None, 1)[1].strip()
    return await verify_supabase_access_token(token)
