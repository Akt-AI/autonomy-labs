from __future__ import annotations

from typing import Any


def normalize_error(
    detail: Any,
    *,
    status_code: int | None = None,
    default_code: str = "http_error",
) -> dict[str, Any]:
    """
    Normalize FastAPI/Starlette error "detail" into a consistent shape.

    Shape:
      {"code": str, "message": str, "status": int|None, "details": Any|None}
    """
    if isinstance(detail, dict):
        code = str(detail.get("code") or default_code)
        message = str(detail.get("message") or detail.get("detail") or "Error")
        details = detail.get("details")
        return {"code": code, "message": message, "status": status_code, "details": details}
    if isinstance(detail, list):
        return {"code": default_code, "message": "Validation error", "status": status_code, "details": detail}
    if detail is None:
        return {"code": default_code, "message": "Error", "status": status_code, "details": None}
    return {"code": default_code, "message": str(detail), "status": status_code, "details": None}

