from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as app_main
from app.db import Base, get_session


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "bootstrap-key")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_READS", "1")
    monkeypatch.setenv("AGENT_HUB_METRICS_REQUIRE_TOKEN", "1")
    monkeypatch.setenv("AGENT_HUB_METRICS_BEARER_TOKEN", "metrics-token-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("AGENT_HUB_JWT_SECRET", "test-jwt-secret-1234567890-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS", "1")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")

    db_path = tmp_path / "test_read_auth.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_session():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app_main._rate_limiter = None
    app_main._rate_limiter_rpm = None

    app_main.app.dependency_overrides[get_session] = override_get_session
    with TestClient(app_main.app) as test_client:
        yield test_client
    app_main.app.dependency_overrides.clear()


def test_read_endpoints_require_bearer_token_when_enabled(client: TestClient) -> None:
    create_project_response = client.post(
        "/projects",
        headers={"X-API-Key": "bootstrap-key"},
        json={"name": "read-auth-project", "repo_url": "https://github.com/acme/example", "default_branch": "main"},
    )
    assert create_project_response.status_code == 200

    missing_token_response = client.get("/projects")
    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "Missing bearer token"

    token_response = client.post(
        "/auth/token",
        headers={"X-API-Key": "bootstrap-key"},
        json={"subject": "viewer-user", "role": "viewer"},
    )
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]

    authorized_response = client.get("/projects", headers={"Authorization": f"Bearer {token}"})
    assert authorized_response.status_code == 200
    assert len(authorized_response.json()) == 1


def test_health_endpoint_remains_public_with_read_auth_enabled(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ui_endpoint_remains_public_with_read_auth_enabled(client: TestClient) -> None:
    response = client.get("/ui")
    assert response.status_code == 200
    assert "Agent Hub API Console" in response.text
    assert "Send Request" in response.text


def test_metrics_endpoint_requires_metrics_bearer_token(client: TestClient) -> None:
    unauthorized = client.get("/metrics")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"] == "Invalid or missing metrics bearer token"

    authorized = client.get(
        "/metrics",
        headers={"Authorization": "Bearer metrics-token-abcdefghijklmnopqrstuvwxyz"},
    )
    assert authorized.status_code == 200
    assert "agent_hub_projects_total" in authorized.text
