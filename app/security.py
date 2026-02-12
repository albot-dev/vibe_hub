from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import get_settings



def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if not value:
        return None
    parts = value.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].strip().lower(), parts[1].strip()
    if scheme != "bearer" or not token:
        return None
    return token



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

    provided_key = (x_api_key or "").strip() or (_extract_bearer_token(authorization) or "").strip()
    if provided_key not in keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
