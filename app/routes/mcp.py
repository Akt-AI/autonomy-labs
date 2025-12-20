from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.settings import feature_enabled

router = APIRouter()


@router.get("/api/mcp/tools")
async def mcp_tools_list(http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail="MCP is disabled")
    _ = await require_user_from_request(http_request)
    try:
        result = await http_request.app.state.codex_mcp_client.list_tools()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class McpCallRequest(BaseModel):
    name: str
    arguments: dict


@router.post("/api/mcp/call")
async def mcp_tools_call(request: McpCallRequest, http_request: Request):
    if not feature_enabled("mcp"):
        raise HTTPException(status_code=403, detail="MCP is disabled")
    _ = await require_user_from_request(http_request)
    try:
        return await http_request.app.state.codex_mcp_client.call_tool(request.name, request.arguments)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
