from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_user_from_request
from app.settings import feature_enabled

router = APIRouter()


class WebCrawlRequest(BaseModel):
    url: str
    maxPages: int = 25
    maxDepth: int = 2
    rateLimitSec: float = 0.25
    respectRobots: bool = True


@router.get("/api/indexing/jobs")
async def list_indexing_jobs(http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Indexing is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store = http_request.app.state.index_job_store
    jobs = await store.list_jobs(user_id)
    # Newest first
    jobs.sort(key=lambda j: str(j.get("createdAt") or ""), reverse=True)
    return {"jobs": jobs}


@router.post("/api/indexing/jobs/web-crawl")
async def start_web_crawl(body: WebCrawlRequest, http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Indexing is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store = http_request.app.state.index_job_store
    job = await store.create_web_crawl_job(
        user_id,
        start_url=body.url,
        max_pages=body.maxPages,
        max_depth=body.maxDepth,
        rate_limit_sec=body.rateLimitSec,
        respect_robots=body.respectRobots,
    )
    return {"ok": True, "job": job.__dict__}


@router.post("/api/indexing/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, http_request: Request):
    if not feature_enabled("indexing"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Indexing is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    store = http_request.app.state.index_job_store
    ok = await store.cancel_job(user_id, job_id)
    return {"ok": True, "canceled": ok}

