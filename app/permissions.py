from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Header, HTTPException

from app.auth import (
    AuthConfigurationError,
    AuthPrincipal,
    Role,
    TokenExpiredError,
    TokenMalformedError,
    verify_access_token,
)
from app.http_auth import extract_bearer_token


def _bearer_401(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _resolve_current_principal(*, optional: bool, authorization: str | None) -> AuthPrincipal | None:
    token = extract_bearer_token(authorization)
    if token is None:
        if optional:
            return None
        raise _bearer_401("Missing bearer token")

    try:
        return verify_access_token(token)
    except TokenExpiredError as exc:
        raise _bearer_401("Token expired") from exc
    except TokenMalformedError:
        raise _bearer_401("Malformed bearer token")
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def get_current_principal(optional: bool = False) -> Callable[..., AuthPrincipal | None]:
    def dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> AuthPrincipal | None:
        return _resolve_current_principal(optional=optional, authorization=authorization)

    return dependency


def require_roles(*roles: Role | str) -> Callable[[AuthPrincipal], AuthPrincipal]:
    if not roles:
        raise ValueError("require_roles() expects at least one role")

    normalized_roles = tuple(Role(role) if isinstance(role, str) else role for role in roles)

    def dependency(principal: AuthPrincipal = Depends(get_current_principal())) -> AuthPrincipal:
        if principal.has_any_role(*normalized_roles):
            return principal

        allowed = ", ".join(role.value for role in normalized_roles)
        raise HTTPException(status_code=403, detail=f"Insufficient role. Requires one of: {allowed}")

    return dependency
