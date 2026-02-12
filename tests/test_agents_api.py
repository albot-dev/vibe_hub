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
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS", "1")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")
    monkeypatch.setenv("AGENT_HUB_WORKSPACES", str(tmp_path / "workspaces"))
    monkeypatch.delenv("AGENT_HUB_TEST_CMD", raising=False)

    db_path = tmp_path / "test_agents_api.db"
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


def _create_project(client: TestClient, name: str, repo_url: str, headers: dict[str, str] | None = None) -> int:
    response = client.post(
        "/projects",
        headers=headers,
        json={"name": name, "repo_url": repo_url, "default_branch": "main"},
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def test_agents_create_list_update_and_project_scoping(client: TestClient, local_repo: str) -> None:
    project_one_id = _create_project(client, "agents-project-one", local_repo)
    project_two_id = _create_project(client, "agents-project-two", local_repo)

    created = client.post(
        f"/projects/{project_one_id}/agents",
        json={
            "name": "Ops Coder",
            "role": "coder",
            "max_parallel_tasks": 3,
            "capabilities": "API maintenance and refactors",
        },
    )
    assert created.status_code == 200
    created_data = created.json()
    assert created_data["project_id"] == project_one_id
    assert created_data["name"] == "Ops Coder"
    assert created_data["role"] == "coder"
    assert created_data["status"] == "active"
    assert created_data["max_parallel_tasks"] == 3
    agent_id = int(created_data["id"])

    listed_project_one = client.get(f"/projects/{project_one_id}/agents")
    assert listed_project_one.status_code == 200
    list_one_data = listed_project_one.json()
    assert len(list_one_data) == 1
    assert list_one_data[0]["id"] == agent_id

    listed_project_two = client.get(f"/projects/{project_two_id}/agents")
    assert listed_project_two.status_code == 200
    assert listed_project_two.json() == []

    updated = client.patch(
        f"/projects/{project_one_id}/agents/{agent_id}",
        json={"name": "Ops Coder II", "max_parallel_tasks": 4, "status": "paused"},
    )
    assert updated.status_code == 200
    updated_data = updated.json()
    assert updated_data["name"] == "Ops Coder II"
    assert updated_data["max_parallel_tasks"] == 4
    assert updated_data["status"] == "paused"

    wrong_project = client.patch(
        f"/projects/{project_two_id}/agents/{agent_id}",
        json={"status": "active"},
    )
    assert wrong_project.status_code == 404
    assert wrong_project.json()["detail"] == "Agent not found"

    missing_project = client.get("/projects/999999/agents")
    assert missing_project.status_code == 404
    assert missing_project.json()["detail"] == "Project not found"


def test_agent_schema_validation_for_name_and_parallelism_bounds(client: TestClient, local_repo: str) -> None:
    project_id = _create_project(client, "agents-validation-project", local_repo)

    invalid_name = client.post(
        f"/projects/{project_id}/agents",
        json={"name": "x", "role": "coder"},
    )
    assert invalid_name.status_code == 422

    invalid_parallel_on_create = client.post(
        f"/projects/{project_id}/agents",
        json={"name": "Valid Agent", "role": "coder", "max_parallel_tasks": 0},
    )
    assert invalid_parallel_on_create.status_code == 422

    created = client.post(
        f"/projects/{project_id}/agents",
        json={"name": "Valid Agent", "role": "coder", "max_parallel_tasks": 2},
    )
    assert created.status_code == 200
    agent_id = int(created.json()["id"])

    invalid_parallel_on_update = client.patch(
        f"/projects/{project_id}/agents/{agent_id}",
        json={"max_parallel_tasks": 21},
    )
    assert invalid_parallel_on_update.status_code == 422


def test_agents_write_endpoints_require_api_key_when_enabled(
    client: TestClient,
    local_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "agent-key")

    headers = {"X-API-Key": "agent-key"}
    project_id = _create_project(client, "agents-api-key-project", local_repo, headers=headers)

    blocked_create = client.post(
        f"/projects/{project_id}/agents",
        json={"name": "Blocked Agent", "role": "planner"},
    )
    assert blocked_create.status_code == 401

    allowed_create = client.post(
        f"/projects/{project_id}/agents",
        headers=headers,
        json={"name": "Allowed Agent", "role": "planner"},
    )
    assert allowed_create.status_code == 200
    agent_id = int(allowed_create.json()["id"])

    blocked_update = client.patch(
        f"/projects/{project_id}/agents/{agent_id}",
        json={"status": "paused"},
    )
    assert blocked_update.status_code == 401

    allowed_update = client.patch(
        f"/projects/{project_id}/agents/{agent_id}",
        headers=headers,
        json={"status": "paused"},
    )
    assert allowed_update.status_code == 200
    assert allowed_update.json()["status"] == "paused"

    list_without_key = client.get(f"/projects/{project_id}/agents")
    assert list_without_key.status_code == 200
    assert len(list_without_key.json()) == 1
