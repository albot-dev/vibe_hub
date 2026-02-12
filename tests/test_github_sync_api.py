from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as app_main
from app import models
from app.db import Base, get_session


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")

    db_path = tmp_path / "test_github_sync_api.db"
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
        yield test_client, TestingSessionLocal
    app_main.app.dependency_overrides.clear()


def test_sync_pull_request_to_github_endpoint(client: tuple[TestClient, sessionmaker]) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "github-sync-project",
            "repo_url": "https://github.com/acme/example-repo",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    with session_factory() as db:
        pr = models.PullRequest(
            project_id=project_id,
            work_item_id=None,
            title="[agent] Add tracing support",
            description=(
                "Autonomous agent delivery with real git branch and commit.\n\n"
                "- branch: agent/1-add-tracing\n"
                "- commit: abc123\n"
            ),
            source_branch="agent/1-add-tracing",
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

    class FakeGitHubSyncAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def create_pull_request(self, **kwargs):
            captured["create_pull_request"] = kwargs
            return {"number": 77, "html_url": "https://github.com/acme/example-repo/pull/77"}

        def create_issue_comment(self, **kwargs):
            captured["create_issue_comment"] = kwargs
            return {"id": 9001}

        def set_commit_status(self, **kwargs):
            captured["set_commit_status"] = kwargs
            return {"state": "pending"}

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_main, "GitHubSyncAdapter", FakeGitHubSyncAdapter)

    try:
        sync_resp = test_client.post(
            f"/projects/{project_id}/pull-requests/{pr_id}/github/sync",
            json={
                "issue_number": 12,
                "comment_body": "Autopilot created a linked PR",
                "status_context": "agent-hub/sync",
                "status_description": "Synced to GitHub",
            },
        )
    finally:
        monkeypatch.undo()

    assert sync_resp.status_code == 200
    data = sync_resp.json()
    assert data["github_pr_number"] == 77
    assert data["owner"] == "acme"
    assert data["repo"] == "example-repo"

    assert "create_pull_request" in captured
    assert captured["create_pull_request"]["head"] == "agent/1-add-tracing"
    assert "create_issue_comment" in captured
    assert "set_commit_status" in captured
