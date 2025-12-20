from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import require_user_from_request
from app.settings import feature_enabled
from app.storage import user_data_dir

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _vault_path(user_id: str) -> Path:
    return user_data_dir(user_id) / "vault.json"


class VaultBlob(BaseModel):
    version: int = 1
    # KDF metadata is informational; encryption is client-side.
    kdf: dict = Field(default_factory=dict)
    salt: str
    iv: str
    ciphertext: str
    updatedAt: str | None = None


@router.get("/api/vault")
async def get_vault(http_request: Request):
    if not feature_enabled("vault"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Vault is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")
    path = _vault_path(user_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"ok": True, "exists": True, "vault": data}
    except FileNotFoundError:
        return {"ok": True, "exists": False, "vault": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


@router.put("/api/vault")
async def put_vault(body: VaultBlob, http_request: Request):
    if not feature_enabled("vault"):
        raise HTTPException(status_code=403, detail={"code": "feature_disabled", "message": "Vault is disabled"})
    user = await require_user_from_request(http_request)
    user_id = str(user.get("id") or "")

    # Basic size guard (client-side encryption should keep this small).
    payload = body.model_dump()
    payload["updatedAt"] = _now_iso()
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw) > 300_000:
        raise HTTPException(status_code=413, detail={"code": "too_large", "message": "Vault payload too large"})

    path = _vault_path(user_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except Exception:
            pass
        return {"ok": True, "updatedAt": payload["updatedAt"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e

