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
    _run(["git", "commit", "-m", "chore: initial commit"], cwd=seed_path)
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
    db_path = tmp_path / "test_agent_hub.db"
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


def test_autopilot_happy_path(client: TestClient, tmp_path: Path, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-repo",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    bootstrap_resp = client.post(f"/projects/{project_id}/bootstrap")
    assert bootstrap_resp.status_code == 200
    assert len(bootstrap_resp.json()["created_agents"]) == 4

    objective_resp = client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": (
                "Improve CI reliability; harden auth middleware; "
                "add regression tests for issue triage"
            ),
            "max_work_items": 3,
            "created_by": "system",
        },
    )
    assert objective_resp.status_code == 200
    assert len(objective_resp.json()["created_items"]) == 3

    run_resp = client.post(f"/projects/{project_id}/autopilot/run", json={"max_items": 3})
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["processed_items"] == 3
    assert len(data["created_prs"]) == 3
    assert len(data["merged_pr_ids"]) == 3

    dashboard_resp = client.get(f"/projects/{project_id}/dashboard")
    assert dashboard_resp.status_code == 200
    dashboard = dashboard_resp.json()
    assert dashboard["done_count"] == 3
    assert dashboard["open_pr_count"] == 0
    assert dashboard["merged_pr_count"] == 3

    workspace = tmp_path / "workspaces" / f"project-{project_id}"
    artifact_file = workspace / "agent_notes" / "work_item_1.md"
    assert artifact_file.exists()

    current_branch = _run(["git", "branch", "--show-current"], cwd=workspace)
    assert current_branch == "main"

    latest_message = _run(["git", "log", "--format=%s", "-n", "1"], cwd=workspace)
    assert latest_message.startswith("agent: implement work item")

    runs_resp = client.get(f"/projects/{project_id}/runs")
    assert runs_resp.status_code == 200
    assert len(runs_resp.json()) == 3

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    assert "agent_hub_projects_total" in metrics_resp.text
    assert "agent_hub_autopilot_jobs_stale_recovered_total" in metrics_resp.text
    assert "agent_hub_autopilot_job_worker_loop_errors_total" in metrics_resp.text


def test_project_name_conflict(client: TestClient, local_repo: str) -> None:
    payload = {
        "name": "duplicate-project",
        "repo_url": local_repo,
        "default_branch": "main",
    }
    first = client.post("/projects", json=payload)
    second = client.post("/projects", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409


def test_autopilot_blocks_merge_when_validation_fails(
    client: TestClient,
    local_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_TEST_CMD", "false")

    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-repo-check-fail",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    project_id = project_resp.json()["id"]

    client.post(f"/projects/{project_id}/bootstrap")
    client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": "Add a stricter auth integration test suite",
            "max_work_items": 1,
            "created_by": "system",
        },
    )

    run_resp = client.post(f"/projects/{project_id}/autopilot/run", json={"max_items": 1})
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["processed_items"] == 1
    assert len(data["created_prs"]) == 1
    assert data["merged_pr_ids"] == []

    tester_reviews = [review for review in data["reviews"] if review["decision"] == "request_changes"]
    assert len(tester_reviews) == 1

    dashboard_resp = client.get(f"/projects/{project_id}/dashboard")
    dashboard = dashboard_resp.json()
    assert dashboard["done_count"] == 0
    assert dashboard["open_pr_count"] == 1


def test_policy_endpoint_can_disable_auto_merge(client: TestClient, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-repo-policy-test",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    get_policy = client.get(f"/projects/{project_id}/policy")
    assert get_policy.status_code == 200
    assert get_policy.json()["auto_merge"] is True

    patch_policy = client.patch(
        f"/projects/{project_id}/policy",
        json={"auto_merge": False, "min_review_approvals": 2},
    )
    assert patch_policy.status_code == 200
    assert patch_policy.json()["auto_merge"] is False
    assert patch_policy.json()["min_review_approvals"] == 2

    client.post(f"/projects/{project_id}/bootstrap")
    client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": "Improve build observability for flaky CI paths",
            "max_work_items": 1,
            "created_by": "system",
        },
    )

    run_resp = client.post(f"/projects/{project_id}/autopilot/run", json={"max_items": 1})
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["processed_items"] == 1
    assert run_data["merged_pr_ids"] == []

    dashboard = client.get(f"/projects/{project_id}/dashboard").json()
    assert dashboard["done_count"] == 0
    assert dashboard["open_pr_count"] == 1


def test_policy_auto_assign_disabled_skips_unassigned(client: TestClient, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-repo-no-auto-assign",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    client.post(f"/projects/{project_id}/bootstrap")
    client.patch(
        f"/projects/{project_id}/policy",
        json={"auto_assign": False},
    )
    client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": "Add distributed tracing around merge queue",
            "max_work_items": 1,
            "created_by": "system",
        },
    )

    run_resp = client.post(f"/projects/{project_id}/autopilot/run", json={"max_items": 1})
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["processed_items"] == 0
    assert run_data["created_prs"] == []
    assert run_data["merged_pr_ids"] == []

    backlog_items = client.get(
        f"/projects/{project_id}/work-items",
        params={"status": "backlog"},
    ).json()
    assert len(backlog_items) == 1


def test_write_endpoints_require_api_key_when_enabled(client: TestClient, local_repo: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "top-secret-key")

    blocked = client.post(
        "/projects",
        json={
            "name": "agent-auth-blocked",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert blocked.status_code == 401

    allowed = client.post(
        "/projects",
        headers={"X-API-Key": "top-secret-key"},
        json={
            "name": "agent-auth-allowed",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert allowed.status_code == 200


def test_local_repo_path_can_be_disabled(client: TestClient, local_repo: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS", "0")

    resp = client.post(
        "/projects",
        json={
            "name": "agent-no-local-paths",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert resp.status_code == 422


def test_manual_assignment_enables_execution_when_auto_assign_disabled(client: TestClient, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-manual-assignment",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    project_id = project_resp.json()["id"]
    bootstrap = client.post(f"/projects/{project_id}/bootstrap").json()
    coder_id = next(agent["id"] for agent in bootstrap["created_agents"] if agent["role"] == "coder")

    client.patch(f"/projects/{project_id}/policy", json={"auto_assign": False})
    create_objective = client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": "Harden request-id propagation middleware",
            "max_work_items": 1,
            "created_by": "system",
        },
    ).json()
    work_item_id = create_objective["created_items"][0]["id"]

    assign = client.patch(
        f"/projects/{project_id}/work-items/{work_item_id}/assign",
        json={"agent_id": coder_id},
    )
    assert assign.status_code == 200
    assert assign.json()["assigned_agent_id"] == coder_id

    run_resp = client.post(f"/projects/{project_id}/autopilot/run", json={"max_items": 1})
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["processed_items"] == 1
    assert len(data["merged_pr_ids"]) == 1


def test_rate_limit_restricts_write_endpoints(client: TestClient, local_repo: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_REQUESTS_PER_MINUTE", "1")

    first = client.post(
        "/projects",
        json={
            "name": "agent-rate-limit-first",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/projects",
        json={
            "name": "agent-rate-limit-second",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert second.status_code == 429

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    line = next(
        (raw for raw in metrics.text.splitlines() if raw.startswith("agent_hub_rate_limit_rejections_total ")),
        "",
    )
    assert line
    value = float(line.split(" ", 1)[1])
    assert value >= 1.0


def test_rate_limit_uses_forwarded_for_when_enabled(
    client: TestClient,
    local_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_REQUESTS_PER_MINUTE", "1")
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("AGENT_HUB_TRUSTED_PROXY_IPS", "testclient")

    first = client.post(
        "/projects",
        headers={"X-Forwarded-For": "203.0.113.10"},
        json={
            "name": "agent-rate-limit-forwarded-first",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/projects",
        headers={"X-Forwarded-For": "198.51.100.20"},
        json={
            "name": "agent-rate-limit-forwarded-second",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert second.status_code == 200

    third = client.post(
        "/projects",
        headers={"X-Forwarded-For": "203.0.113.10"},
        json={
            "name": "agent-rate-limit-forwarded-third",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert third.status_code == 429


def test_rate_limit_ignores_forwarded_for_from_untrusted_clients(
    client: TestClient,
    local_repo: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_REQUESTS_PER_MINUTE", "1")
    monkeypatch.setenv("AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS", "1")
    monkeypatch.setenv("AGENT_HUB_TRUSTED_PROXY_IPS", "10.0.0.10")

    first = client.post(
        "/projects",
        headers={"X-Forwarded-For": "203.0.113.10"},
        json={
            "name": "agent-rate-limit-untrusted-first",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/projects",
        headers={"X-Forwarded-For": "198.51.100.20"},
        json={
            "name": "agent-rate-limit-untrusted-second",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    assert second.status_code == 429


def test_autopilot_rejects_unknown_provider_override(client: TestClient, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-provider-override-test",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    project_id = project_resp.json()["id"]
    client.post(f"/projects/{project_id}/bootstrap")
    client.post(
        f"/projects/{project_id}/objectives",
        json={
            "objective": "Improve planner prompts for issue decomposition",
            "max_work_items": 1,
            "created_by": "system",
        },
    )

    run_resp = client.post(
        f"/projects/{project_id}/autopilot/run",
        json={"max_items": 1, "provider": "does-not-exist"},
    )
    assert run_resp.status_code == 422


def test_autopilot_job_endpoints_queue_and_cancel(client: TestClient, local_repo: str) -> None:
    project_resp = client.post(
        "/projects",
        json={
            "name": "agent-job-endpoints",
            "repo_url": local_repo,
            "default_branch": "main",
        },
    )
    project_id = project_resp.json()["id"]
    client.post(f"/projects/{project_id}/bootstrap")

    enqueue_resp = client.post(
        f"/projects/{project_id}/jobs/autopilot",
        json={"max_items": 2, "requested_by": "api-test", "max_attempts": 2},
    )
    assert enqueue_resp.status_code == 200
    job = enqueue_resp.json()
    assert job["status"] == "queued"
    job_id = job["id"]

    listed = client.get(f"/projects/{project_id}/jobs").json()
    assert len(listed) == 1
    assert listed[0]["id"] == job_id

    fetched = client.get(f"/projects/{project_id}/jobs/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["requested_by"] == "api-test"

    retry_invalid = client.post(f"/projects/{project_id}/jobs/{job_id}/retry")
    assert retry_invalid.status_code == 409

    canceled = client.post(f"/projects/{project_id}/jobs/{job_id}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    retried = client.post(f"/projects/{project_id}/jobs/{job_id}/retry")
    assert retried.status_code == 200
    retry_job = retried.json()
    assert retry_job["status"] == "queued"
    assert retry_job["attempts"] == 0
    assert retry_job["canceled_at"] is None
