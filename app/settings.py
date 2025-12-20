from __future__ import annotations

import os


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
    defaults = {
        "terminal": has_supabase,
        "codex": has_supabase,
        "mcp": has_supabase,
        "indexing": False,
    }
    env_map = {
        "terminal": "ENABLE_TERMINAL",
        "codex": "ENABLE_CODEX",
        "mcp": "ENABLE_MCP",
        "indexing": "ENABLE_INDEXING",
    }
    if feature not in env_map:
        return False
    return env_truthy(env_map[feature], default=defaults[feature])

