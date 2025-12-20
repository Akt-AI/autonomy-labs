from __future__ import annotations

import os
from pathlib import Path


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def user_data_dir(user_id: str) -> Path:
    """
    Returns a per-user writable directory for server-side persistence.

    Prefers `/data` (HF Spaces) and falls back to `~/.autonomy-labs`.
    """
    user_id = (user_id or "").strip() or "unknown"

    preferred = Path("/data") / "autonomy-labs" / "users" / user_id
    if preferred.parent.exists() and _writable_dir(preferred):
        return preferred

    fallback = Path(os.path.expanduser("~")) / ".autonomy-labs" / "users" / user_id
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

