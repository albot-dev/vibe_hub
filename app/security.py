from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import get_settings
from app.http_auth import extract_bearer_token



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
    if provided_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
