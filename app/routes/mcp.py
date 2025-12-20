from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.mcp_policy import load_mcp_policy, tool_allowed
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
