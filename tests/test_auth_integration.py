from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as app_main
from app.db import Base, get_session


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


@pytest.fixture()
def local_repo(tmp_path: Path) -> str:
    remote_path = tmp_path / "remote.git"
    seed_path = tmp_path / "seed_repo"
    seed_path.mkdir(parents=True, exist_ok=True)

    _run(["git", "init", "--bare", str(remote_path)], cwd=tmp_path)
    _run(["git", "init", "-b", "main"], cwd=seed_path)
    _run(["git", "config", "user.name", "Test Bot"], cwd=seed_path)
    _run(["git", "config", "user.email", "test@example.local"], cwd=seed_path)
    (seed_path / "README.md").write_text("# Seed Repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed_path)
    _run(["git", "commit", "-m", "chore: init"], cwd=seed_path)
    _run(["git", "remote", "add", "origin", str(remote_path)], cwd=seed_path)
    _run(["git", "push", "-u", "origin", "main"], cwd=seed_path)
    return str(remote_path)


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "bootstrap-key")
    monkeypatch.setenv("AGENT_HUB_JWT_SECRET", "test-jwt-secret-1234567890-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "1")
    monkeypatch.setenv("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS", "1")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")
    monkeypatch.setenv("AGENT_HUB_WORKSPACES", str(tmp_path / "workspaces"))
    monkeypatch.delenv("AGENT_HUB_TEST_CMD", raising=False)

    db_path = tmp_path / "test_auth_api.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_session():
        db = TestingSessionLocal()
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


def test_auth_token_and_role_enforcement(client: TestClient, local_repo: str) -> None:
    maintainer_token_resp = client.post(
        "/auth/token",
        headers={"X-API-Key": "bootstrap-key"},
        json={"subject": "maintainer-user", "role": "maintainer"},
    )
    assert maintainer_token_resp.status_code == 200
    maintainer_token = maintainer_token_resp.json()["access_token"]

    viewer_token_resp = client.post(
        "/auth/token",
        headers={"X-API-Key": "bootstrap-key"},
        json={"subject": "viewer-user", "role": "viewer"},
    )
    assert viewer_token_resp.status_code == 200
    viewer_token = viewer_token_resp.json()["access_token"]

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {maintainer_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "maintainer"

    project_resp = client.post(
        "/projects",
        headers={
            "X-API-Key": "bootstrap-key",
            "Authorization": f"Bearer {maintainer_token}",
        },
        json={"name": "authz-project", "repo_url": local_repo, "default_branch": "main"},
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    bootstrap_resp = client.post(
        f"/projects/{project_id}/bootstrap",
        headers={
            "X-API-Key": "bootstrap-key",
            "Authorization": f"Bearer {maintainer_token}",
        },
    )
    assert bootstrap_resp.status_code == 200

    objective_resp = client.post(
        f"/projects/{project_id}/objectives",
        headers={
            "X-API-Key": "bootstrap-key",
            "Authorization": f"Bearer {maintainer_token}",
        },
        json={
            "objective": "Strengthen auth integration coverage in workflow",
            "max_work_items": 1,
            "created_by": "system",
        },
    )
    assert objective_resp.status_code == 200

    missing_token = client.post(
        f"/projects/{project_id}/autopilot/run",
        headers={"X-API-Key": "bootstrap-key"},
        json={"max_items": 1},
    )
    assert missing_token.status_code == 401

    viewer_forbidden = client.post(
        f"/projects/{project_id}/autopilot/run",
        headers={
            "X-API-Key": "bootstrap-key",
            "Authorization": f"Bearer {viewer_token}",
        },
        json={"max_items": 1},
    )
    assert viewer_forbidden.status_code == 403

    maintainer_allowed = client.post(
        f"/projects/{project_id}/autopilot/run",
        headers={
            "X-API-Key": "bootstrap-key",
            "Authorization": f"Bearer {maintainer_token}",
        },
        json={"max_items": 1},
    )
    assert maintainer_allowed.status_code == 200
