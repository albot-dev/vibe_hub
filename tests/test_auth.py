from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.auth import (
    AuthConfigurationError,
    AuthPrincipal,
    JWT_SECRET_ENV,
    JWT_TTL_SECONDS_ENV,
    Role,
    TokenExpiredError,
    TokenMalformedError,
    issue_access_token,
    verify_access_token,
)
from app.permissions import get_current_principal, require_roles


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _clear_jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JWT_SECRET_ENV, raising=False)
    monkeypatch.delenv(JWT_TTL_SECONDS_ENV, raising=False)


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/optional")
    def optional_endpoint(
        principal: AuthPrincipal | None = Depends(get_current_principal(optional=True)),
    ) -> dict[str, str | None]:
        return {"subject": principal.subject if principal else None}

    @app.get("/admin")
    def admin_endpoint(_: AuthPrincipal = Depends(require_roles(Role.admin))) -> dict[str, bool]:
        return {"ok": True}

    return app


def test_issue_and_verify_access_token_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, "test-secret-with-at-least-32-bytes-123")
    monkeypatch.setenv(JWT_TTL_SECONDS_ENV, "600")

    principal = AuthPrincipal(subject="user-123", role=Role.maintainer)
    token = issue_access_token(principal)
    verified = verify_access_token(token)

    assert verified.subject == "user-123"
    assert verified.role is Role.maintainer
    assert verified.has_role(Role.viewer)
    assert not verified.has_role(Role.admin)


def test_issue_access_token_requires_secret() -> None:
    principal = AuthPrincipal(subject="user-123", role=Role.viewer)
    with pytest.raises(AuthConfigurationError, match="Missing JWT secret"):
        issue_access_token(principal)


def test_verify_access_token_rejects_malformed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, "test-secret-with-at-least-32-bytes-123")
    with pytest.raises(TokenMalformedError):
        verify_access_token("not-a-jwt")


def test_verify_access_token_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, "test-secret-with-at-least-32-bytes-123")
    principal = AuthPrincipal(subject="user-123", role=Role.viewer)
    token = issue_access_token(principal, expires_in_seconds=-1)

    with pytest.raises(TokenExpiredError):
        verify_access_token(token)


def test_verify_access_token_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JWT_SECRET_ENV, raising=False)
    token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJ1c2VyLTEyMyIsInJvbGUiOiJ2aWV3ZXIiLCJleHAiOjQ3NjczNjY0MDAsImlhdCI6MTcwMDAwMDAwMH0."
        "invalidsignature"
    )
    with pytest.raises(AuthConfigurationError, match="Missing JWT secret"):
        verify_access_token(token)


def test_get_current_principal_optional_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, "test-secret-with-at-least-32-bytes-123")
    app = _build_test_app()
    client = TestClient(app)

    no_auth = client.get("/optional")
    assert no_auth.status_code == 200
    assert no_auth.json() == {"subject": None}

    token = issue_access_token(AuthPrincipal(subject="viewer-user", role=Role.viewer))
    with_auth = client.get("/optional", headers=_auth_header(token))
    assert with_auth.status_code == 200
    assert with_auth.json() == {"subject": "viewer-user"}


def test_require_roles_enforces_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, "test-secret-with-at-least-32-bytes-123")
    app = _build_test_app()
    client = TestClient(app)

    missing = client.get("/admin")
    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing bearer token"

    malformed = client.get("/admin", headers=_auth_header("bad-token"))
    assert malformed.status_code == 401
    assert malformed.json()["detail"] == "Malformed bearer token"

    viewer_token = issue_access_token(AuthPrincipal(subject="viewer-user", role=Role.viewer))
    forbidden = client.get("/admin", headers=_auth_header(viewer_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "Insufficient role. Requires one of: admin"

    admin_token = issue_access_token(AuthPrincipal(subject="admin-user", role=Role.admin))
    allowed = client.get("/admin", headers=_auth_header(admin_token))
    assert allowed.status_code == 200
    assert allowed.json() == {"ok": True}
