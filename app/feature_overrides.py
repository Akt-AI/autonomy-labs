from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.storage import global_data_dir

_LOCK = threading.Lock()
_CACHE_AT: float = 0.0
_CACHE: dict[str, bool] = {}
_TTL_SEC = 3.0
_PATH = global_data_dir() / "feature-overrides.json"


def load_feature_overrides() -> dict[str, bool]:
    """
    Loads persisted feature overrides (admin-managed).

    Shape: {"version": 1, "overrides": {"terminal": true, "mcp": false, ...}}
    """
    global _CACHE_AT, _CACHE
    now = time.monotonic()
    if now - _CACHE_AT < _TTL_SEC:
        return dict(_CACHE)

    with _LOCK:
        now = time.monotonic()
        if now - _CACHE_AT < _TTL_SEC:
            return dict(_CACHE)
        path = _PATH
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _CACHE = {}
            _CACHE_AT = now
            return {}
        except Exception:
            _CACHE_AT = now
            return dict(_CACHE)

        overrides = data.get("overrides") if isinstance(data, dict) else None
        out: dict[str, bool] = {}
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                key = str(k).strip()
                if not key:
                    continue
                if isinstance(v, bool):
                    out[key] = v
        _CACHE = out
        _CACHE_AT = now
        return dict(_CACHE)


def save_feature_overrides(overrides: dict[str, Any]) -> dict[str, bool]:
    """
    Persists a partial or full overrides dict (values must be bool).
    """
    global _CACHE_AT, _CACHE
    out: dict[str, bool] = {}
    for k, v in (overrides or {}).items():
        key = str(k).strip()
        if not key:
            continue
        if isinstance(v, bool):
            out[key] = v

    payload = {"version": 1, "overrides": out}
    path = _PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with _LOCK:
        _CACHE = dict(out)
        _CACHE_AT = time.monotonic()
    return out
