from __future__ import annotations

from time import monotonic

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.mcp_policy import load_mcp_policy, tool_allowed
from app.net_safety import validate_public_http_url
from app.settings import feature_enabled

router = APIRouter()


@router.get("/api/mcp/tools")
async def mcp_tools_list(http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "MCP is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    try:
        policy = load_mcp_policy(user_id)
        result = await http_request.app.state.codex_mcp_client.list_tools()
        tools = None
        if isinstance(result, dict) and isinstance(result.get("tools"), list):
            tools = result.get("tools")
        if tools is None:
            return result
        filtered = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()
            if tool_allowed(name, policy):
                filtered.append(t)
        return {**result, "tools": filtered}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "mcp_error", "message": str(e)}) from e


class McpCallRequest(BaseModel):
    name: str
    arguments: dict


class McpTestRequest(BaseModel):
    url: str
    headers: dict[str, str] | None = None
    timeoutSec: float = 3.0


@router.post("/api/mcp/call")
async def mcp_tools_call(request: McpCallRequest, http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "MCP is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    try:
        policy = load_mcp_policy(user_id)
        if not tool_allowed(request.name, policy):
            raise HTTPException(
                status_code=403,
                detail={"code": "tool_denied", "message": f"MCP tool not allowed: {request.name}"},
            )
        return await http_request.app.state.codex_mcp_client.call_tool(request.name, request.arguments)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "mcp_error", "message": str(e)}) from e


@router.post("/api/mcp/test")
async def mcp_test(request: McpTestRequest, http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "MCP is disabled"})
    _ = await require_user_from_request(http_request)

    url = validate_public_http_url(request.url)
    timeout = float(request.timeoutSec or 3.0)
    timeout = max(0.5, min(timeout, 8.0))

    raw_headers = request.headers if isinstance(request.headers, dict) else {}
    headers: dict[str, str] = {}
    for k, v in raw_headers.items():
        key = str(k).strip()
        if not key:
            continue
        lk = key.lower()
        if lk in {"host", "content-length", "connection"}:
            continue
        if len(key) > 80:
            continue
        val = str(v).strip()
        if len(val) > 2000:
            val = val[:2000]
        headers[key] = val

    start = monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                limit = 1024
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    if len(buf) >= limit:
                        break
        elapsed_ms = int((monotonic() - start) * 1000)
        preview = bytes(buf[:1024]).decode("utf-8", errors="ignore").strip()
        return {
            "ok": True,
            "url": url,
            "statusCode": resp.status_code,
            "contentType": resp.headers.get("content-type"),
            "elapsedMs": elapsed_ms,
            "preview": preview[:500],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "mcp_test_failed", "message": str(e)}) from e
