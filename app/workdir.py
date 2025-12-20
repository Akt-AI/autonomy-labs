from __future__ import annotations

import os
from typing import Any, Optional


def safe_user_workdir(user: dict[str, Any], requested: Optional[str]) -> str:
    """
    Restrict Codex workdir to an allowlisted root to prevent traversal.
    """
    base_root = "/data/codex/workspace" if os.path.isdir("/data") else "/app"
    user_id = (user.get("id") or "").strip()
    user_root = os.path.join(base_root, user_id) if user_id else base_root

    if requested:
        req = requested.strip()
        if req:
            norm = os.path.normpath(req)
            if os.path.isabs(norm):
                candidate = norm
            else:
                candidate = os.path.join(user_root, norm)
            candidate = os.path.normpath(candidate)
            base_norm = os.path.normpath(base_root)
            if candidate == base_norm or candidate.startswith(base_norm + os.sep):
                os.makedirs(candidate, exist_ok=True)
                return candidate

    os.makedirs(user_root, exist_ok=True)
    return user_root

