from __future__ import annotations

import os

from app.feature_overrides import load_feature_overrides


def env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def feature_enabled(feature: str) -> bool:
    """
    Safety: when Supabase isn't configured, disable dangerous features by default.
    """
    has_supabase = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))
    if not has_supabase:
        return False
    defaults = {
        "terminal": True,
        "codex": True,
        "mcp": True,
        "indexing": False,
        "rooms": True,
    }
    env_map = {
        "terminal": "ENABLE_TERMINAL",
        "codex": "ENABLE_CODEX",
        "mcp": "ENABLE_MCP",
        "indexing": "ENABLE_INDEXING",
        "rooms": "ENABLE_ROOMS",
    }
    if feature not in env_map:
        return False

    env_enabled = env_truthy(env_map[feature], default=defaults[feature])
    overrides = load_feature_overrides()
    if feature in overrides:
        return bool(overrides[feature])
    return env_enabled
