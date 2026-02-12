from __future__ import annotations


def extract_bearer_token(authorization: str | None) -> str | None:
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

