from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    # OpenAI-compatible: content can be plain text or an array of multimodal parts.
    content: str | list[Any]


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    apiKey: str | None = None
    baseUrl: str | None = None
    model: str | None = "gpt-3.5-turbo"


@router.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    api_key = request.apiKey or os.environ.get("OPENAI_API_KEY")
    base_url = request.baseUrl or os.environ.get("OPENAI_BASE_URL")

    if not api_key:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "API Key is required"})

    client = OpenAI(api_key=api_key, base_url=base_url)

    def generate():
        try:
            stream = client.chat.completions.create(
                model=request.model,
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
                stream=True,
            )
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"Error: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain")


class ModelsRequest(BaseModel):
    apiKey: str | None = None
    baseUrl: str | None = None


@router.post("/api/proxy/models")
async def proxy_models(request: ModelsRequest):
    api_key = request.apiKey or os.environ.get("OPENAI_API_KEY")
    base_url = request.baseUrl or os.environ.get("OPENAI_BASE_URL")

    if not base_url:
        raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": "Base URL is required"})

    try:
        import httpx

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        target_url = f"{base_url.rstrip('/')}/models"

        async with httpx.AsyncClient() as client:
            resp = await client.get(target_url, headers=headers, timeout=10.0)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail={
                        "code": "provider_error",
                        "message": "Provider returned error",
                        "details": {"status": resp.status_code, "body": resp.text[:4000]},
                    },
                )
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e
