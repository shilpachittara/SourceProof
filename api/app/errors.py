"""Structured API error responses (verifier-API SEP error-1.0 aligned)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
    *,
    headers: Optional[dict[str, str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> HTTPException:
    detail: dict[str, Any] = {"code": code, "message": message}
    if extra:
        detail.update(extra)
    return HTTPException(status_code=status_code, detail=detail, headers=headers)
