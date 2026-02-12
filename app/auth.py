from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from pydantic import BaseModel, Field, ValidationError

JWT_SECRET_ENV = "AGENT_HUB_JWT_SECRET"
JWT_TTL_SECONDS_ENV = "AGENT_HUB_JWT_TTL_SECONDS"
JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 3600


class AuthError(Exception):
    """Base auth error."""


class AuthConfigurationError(AuthError):
    """Raised when auth configuration is invalid."""


class TokenMalformedError(AuthError):
    """Raised when a token cannot be decoded or validated."""


class TokenExpiredError(AuthError):
    """Raised when a token is expired."""


class Role(str, Enum):
    admin = "admin"
    maintainer = "maintainer"
    viewer = "viewer"


_ROLE_LEVELS = {
    Role.viewer: 1,
    Role.maintainer: 2,
    Role.admin: 3,
}


class AuthPrincipal(BaseModel):
    subject: str = Field(min_length=1)
    role: Role

    def has_role(self, role: Role | str) -> bool:
        required = Role(role)
        return _ROLE_LEVELS[self.role] >= _ROLE_LEVELS[required]

    def has_any_role(self, *roles: Role | str) -> bool:
        if not roles:
            return False
        return any(self.has_role(role) for role in roles)


def get_jwt_secret() -> str:
    secret = os.getenv(JWT_SECRET_ENV, "").strip()
    if not secret:
        raise AuthConfigurationError(f"Missing JWT secret in {JWT_SECRET_ENV}")
    return secret


def get_token_ttl_seconds() -> int:
    raw_value = os.getenv(JWT_TTL_SECONDS_ENV, "").strip()
    if not raw_value:
        return DEFAULT_TOKEN_TTL_SECONDS

    try:
        ttl_seconds = int(raw_value)
    except ValueError as exc:
        raise AuthConfigurationError(
            f"Invalid token TTL in {JWT_TTL_SECONDS_ENV}: {raw_value!r}",
        ) from exc

    if ttl_seconds <= 0:
        raise AuthConfigurationError(
            f"Invalid token TTL in {JWT_TTL_SECONDS_ENV}: expected a positive integer",
        )
    return ttl_seconds


def _ensure_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def issue_access_token(
    principal: AuthPrincipal,
    *,
    expires_in_seconds: int | None = None,
    now: datetime | None = None,
) -> str:
    secret = get_jwt_secret()
    issued_at = _ensure_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    ttl_seconds = expires_in_seconds if expires_in_seconds is not None else get_token_ttl_seconds()
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": principal.subject,
        "role": principal.role.value,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_access_token(token: str) -> AuthPrincipal:
    if not token or not token.strip():
        raise TokenMalformedError("Token is empty")

    secret = get_jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenMalformedError("Token is malformed or invalid") from exc

    try:
        return AuthPrincipal(subject=payload["sub"], role=payload["role"])
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        raise TokenMalformedError("Token payload is invalid") from exc
