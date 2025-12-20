from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.storage import user_data_dir


def _policy_path(user_id: str) -> Path:
    return user_data_dir(user_id) / "mcp-policy.json"


def load_mcp_policy(user_id: str) -> dict[str, Any]:
    path = _policy_path(user_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Invalid policy")
        allow = data.get("allow")
        deny = data.get("deny")
        return {
            "version": int(data.get("version") or 1),
            "allow": allow if isinstance(allow, list) else [],
            "deny": deny if isinstance(deny, list) else [],
        }
    except FileNotFoundError:
        return {"version": 1, "allow": [], "deny": []}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


def save_mcp_policy(user_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    allow_in = policy.get("allow")
    deny_in = policy.get("deny")

    allow = [str(x).strip() for x in (allow_in or []) if str(x).strip()] if isinstance(allow_in, list) else []
    deny = [str(x).strip() for x in (deny_in or []) if str(x).strip()] if isinstance(deny_in, list) else []

    allow = list(dict.fromkeys(allow))[:500]
    deny = list(dict.fromkeys(deny))[:500]

    payload = {"version": int(policy.get("version") or 1), "allow": allow, "deny": deny}
    path = _policy_path(user_id)
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "internal_error", "message": str(e)}) from e


def tool_allowed(tool_name: str, policy: dict[str, Any]) -> bool:
    name = (tool_name or "").strip()
    if not name:
        return False
    deny = policy.get("deny") if isinstance(policy.get("deny"), list) else []
    allow = policy.get("allow") if isinstance(policy.get("allow"), list) else []
    deny_set = {str(x).strip() for x in deny if str(x).strip()}
    allow_set = {str(x).strip() for x in allow if str(x).strip()}
    if name in deny_set:
        return False
    if allow_set and name not in allow_set:
        return False
    return True

