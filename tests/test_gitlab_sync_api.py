from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as app_main
from app import models
from app.db import Base, get_session
from app.gitlab_sync import GitLabAPIError


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")

    db_path = tmp_path / "test_gitlab_sync_api.db"
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
        yield test_client, testing_session_local
    app_main.app.dependency_overrides.clear()


def test_sync_pull_request_to_gitlab_endpoint(client: tuple[TestClient, sessionmaker]) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "gitlab-sync-project",
            "repo_url": "https://gitlab.com/acme/platform-repo",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    with session_factory() as db:
        pr = models.PullRequest(
            project_id=project_id,
            work_item_id=None,
            title="[agent] Add GitLab sync integration",
            description=(
                "Agent-generated PR metadata.\n\n"
                "- branch: agent/7-gitlab-sync\n"
                "- commit: abc123\n"
            ),
            source_branch="agent/7-gitlab-sync",
            target_branch="main",
            status=models.PullRequestStatus.open,
            checks_passed=True,
            auto_merge=True,
            created_by_agent_id=None,
        )
        db.add(pr)
        db.commit()
        db.refresh(pr)
        pr_id = pr.id

    captured: dict[str, object] = {}

    class FakeGitLabSyncAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def create_merge_request(self, **kwargs):
            captured["create_merge_request"] = kwargs
            return {"iid": 73, "web_url": "https://gitlab.com/acme/platform-repo/-/merge_requests/73"}

        def create_issue_note(self, **kwargs):
            captured["create_issue_note"] = kwargs
            return {"id": 5002}

        def set_commit_status(self, **kwargs):
            captured["set_commit_status"] = kwargs
            return {"status": "pending"}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_main, "GitLabSyncAdapter", FakeGitLabSyncAdapter)

    try:
        sync_resp = test_client.post(
            f"/projects/{project_id}/pull-requests/{pr_id}/gitlab/sync",
            json={
                "issue_iid": 11,
                "comment_body": "Autopilot generated this merge request",
                "status_context": "agent-hub/sync",
                "status_description": "Synced to GitLab",
            },
        )
    finally:
        monkeypatch.undo()

    assert sync_resp.status_code == 200
    data = sync_resp.json()
    assert data["gitlab_mr_iid"] == 73
    assert data["project_path"] == "acme/platform-repo"
    assert data["commit_status_state"] == "pending"

    assert "create_merge_request" in captured
    assert captured["create_merge_request"]["source_branch"] == "agent/7-gitlab-sync"
    assert "create_issue_note" in captured
    assert "set_commit_status" in captured


def test_sync_pull_request_to_gitlab_endpoint_returns_422_for_invalid_project_repo_url(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "gitlab-sync-invalid-repo",
            "repo_url": "ssh://gitlab.com/acme/platform-repo.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    with session_factory() as db:
        pr = models.PullRequest(
            project_id=project_id,
            work_item_id=None,
            title="[agent] Invalid repo URL",
            description="No metadata",
            source_branch="agent/invalid",
            target_branch="main",
            status=models.PullRequestStatus.open,
            checks_passed=True,
            auto_merge=False,
            created_by_agent_id=None,
        )
        db.add(pr)
        db.commit()
        db.refresh(pr)
        pr_id = pr.id

    sync_resp = test_client.post(
        f"/projects/{project_id}/pull-requests/{pr_id}/gitlab/sync",
        json={},
    )
    assert sync_resp.status_code == 422
    assert "Unsupported repository URL scheme" in sync_resp.json()["detail"]


def test_sync_pull_request_to_gitlab_endpoint_maps_gitlab_errors_to_502(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "gitlab-sync-api-error",
            "repo_url": "https://gitlab.com/acme/platform-repo",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    with session_factory() as db:
        pr = models.PullRequest(
            project_id=project_id,
            work_item_id=None,
            title="[agent] API failure path",
            description="- commit: abc123",
            source_branch="agent/failure-path",
            target_branch="main",
            status=models.PullRequestStatus.open,
            checks_passed=True,
            auto_merge=False,
            created_by_agent_id=None,
        )
        db.add(pr)
        db.commit()
        db.refresh(pr)
        pr_id = pr.id

    class FailingGitLabSyncAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def create_merge_request(self, **kwargs):
            raise GitLabAPIError(
                method="POST",
                url="https://gitlab.example/api/v4/projects/acme%2Fplatform-repo/merge_requests",
                status_code=404,
                detail="Project Not Found",
            )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_main, "GitLabSyncAdapter", FailingGitLabSyncAdapter)
    try:
        sync_resp = test_client.post(
            f"/projects/{project_id}/pull-requests/{pr_id}/gitlab/sync",
            json={},
        )
    finally:
        monkeypatch.undo()

    assert sync_resp.status_code == 502
    assert "Project Not Found" in sync_resp.json()["detail"]
