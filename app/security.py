from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.config import get_settings
from app.http_auth import extract_bearer_token


def _matches_any_api_key(provided_key: str, keys: set[str]) -> bool:
    if not provided_key:
        return False
    return any(hmac.compare_digest(provided_key, expected) for expected in keys)


def require_write_access(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    settings = get_settings()
    if not settings.require_api_key:
        return

    keys = settings.parsed_api_keys()
    if not keys:
        raise HTTPException(status_code=500, detail="API key auth enabled but no keys configured")

    provided_key = (x_api_key or "").strip() or (extract_bearer_token(authorization) or "").strip()
    if not _matches_any_api_key(provided_key, keys):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
