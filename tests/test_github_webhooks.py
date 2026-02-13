from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.github_webhooks as github_webhooks
import app.main as app_main
from app import models
from app.db import Base, get_session


def _json_body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _github_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")
    monkeypatch.delenv("AGENT_HUB_GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("AGENT_HUB_GITHUB_WEBHOOK_AUTO_ENQUEUE", raising=False)

    db_path = tmp_path / "test_github_webhooks.db"
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


def test_github_webhook_issues_opened_valid_signature_creates_objective(
    client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session_factory = client
    monkeypatch.setenv("AGENT_HUB_GITHUB_WEBHOOK_SECRET", "webhook-secret")

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "webhook-repo",
            "repo_url": "git@github.com:Acme/Widget.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    payload = {
        "action": "opened",
        "repository": {
            "full_name": "acme/widget",
            "html_url": "https://github.com/acme/widget",
        },
        "issue": {
            "number": 42,
            "title": "Stabilize flaky integration tests",
            "body": "Tests fail intermittently due to timing variance.",
            "html_url": "https://github.com/acme/widget/issues/42",
        },
        "sender": {"login": "octocat"},
    }
    body = _json_body(payload)
    response = test_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-issues-opened-42",
            "X-Hub-Signature-256": _github_signature("webhook-secret", body),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "objective_created"
    assert data["project_id"] == project_id
    assert data["issue_number"] == 42
    assert "Resolve GitHub issue #42" in data["objective"]

    with session_factory() as db:
        items = db.scalars(
            select(models.WorkItem).where(models.WorkItem.project_id == project_id)
        ).all()
    assert len(items) >= 1


def test_github_webhook_invalid_signature_rejected(
    client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _ = client
    monkeypatch.setenv("AGENT_HUB_GITHUB_WEBHOOK_SECRET", "expected-secret")

    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/widget"},
        "issue": {"number": 5, "title": "Something to do"},
    }
    body = _json_body(payload)
    response = test_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-invalid-signature",
            "X-Hub-Signature-256": _github_signature("wrong-secret", body),
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_github_webhook_no_matching_project_returns_no_project(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    payload = {
        "action": "opened",
        "repository": {"full_name": "nope/missing-repo"},
        "issue": {"number": 9, "title": "Investigate timeout"},
    }
    response = test_client.post(
        "/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-no-project",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "no_project"
    assert data["project_id"] is None

    with session_factory() as db:
        items = db.scalars(select(models.WorkItem)).all()
    assert items == []


def test_github_webhook_issue_comment_agent_run_enqueues_job(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "comment-command-repo",
            "repo_url": "https://github.com/acme/widget.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    payload = {
        "action": "created",
        "repository": {
            "name": "widget",
            "owner": {"login": "acme"},
            "url": "https://api.github.com/repos/acme/widget",
        },
        "issue": {
            "number": 77,
            "title": "Enable on-demand run",
            "html_url": "https://github.com/acme/widget/issues/77",
        },
        "comment": {"body": "please execute this\n/agent run\nthanks"},
        "sender": {"login": "trigger-user"},
    }
    response = test_client.post(
        "/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": "delivery-issue-comment-run",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "job_enqueued"
    assert data["project_id"] == project_id
    assert data["issue_number"] == 77
    assert isinstance(data["job_id"], int)

    with session_factory() as db:
        jobs = db.scalars(
            select(models.AutopilotJob).where(models.AutopilotJob.project_id == project_id)
        ).all()
    assert len(jobs) == 1
    assert jobs[0].requested_by == "github:trigger-user"


def test_github_webhook_duplicate_delivery_is_ignored_without_side_effects(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "duplicate-delivery-repo",
            "repo_url": "https://github.com/acme/duplicate-demo.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    payload = {
        "action": "opened",
        "repository": {"full_name": "acme/duplicate-demo"},
        "issue": {
            "number": 123,
            "title": "Create objective exactly once",
        },
    }
    headers = {
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-dedup-123",
    }

    first = test_client.post("/webhooks/github", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["action"] == "objective_created"

    with session_factory() as db:
        first_item_count = len(
            db.scalars(
                select(models.WorkItem).where(models.WorkItem.project_id == project_id)
            ).all()
        )
    assert first_item_count >= 1

    second = test_client.post("/webhooks/github", json=payload, headers=headers)
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["action"] == "ignored"
    assert second_data["reason"] == "Duplicate delivery"

    with session_factory() as db:
        second_item_count = len(
            db.scalars(
                select(models.WorkItem).where(models.WorkItem.project_id == project_id)
            ).all()
        )
        delivery = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-dedup-123"
            )
        )

    assert second_item_count == first_item_count
    assert delivery is not None
    assert delivery.action == "objective_created"
    assert delivery.event == "issues"
    assert delivery.duplicate_count == 1


def test_github_webhook_delivery_records_persist_for_processed_and_ignored(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    project_resp = test_client.post(
        "/projects",
        json={
            "name": "delivery-records-repo",
            "repo_url": "https://github.com/acme/persist-demo.git",
            "default_branch": "main",
        },
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    issues_payload = {
        "action": "opened",
        "repository": {"full_name": "acme/persist-demo"},
        "issue": {"number": 11, "title": "Persist processed delivery"},
    }
    processed = test_client.post(
        "/webhooks/github",
        json=issues_payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-persist-processed",
        },
    )
    assert processed.status_code == 200
    assert processed.json()["action"] == "objective_created"

    ignored_comment_payload = {
        "action": "created",
        "repository": {
            "name": "persist-demo",
            "owner": {"login": "acme"},
        },
        "issue": {"number": 12, "title": "Persist ignored delivery"},
        "comment": {"body": "thanks for the update"},
    }
    ignored = test_client.post(
        "/webhooks/github",
        json=ignored_comment_payload,
        headers={
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": "delivery-persist-ignored",
        },
    )
    assert ignored.status_code == 200
    ignored_data = ignored.json()
    assert ignored_data["action"] == "ignored"
    assert ignored_data["reason"] == "No supported command found"

    with session_factory() as db:
        processed_record = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-persist-processed"
            )
        )
        ignored_record = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-persist-ignored"
            )
        )

    assert processed_record is not None
    assert processed_record.event == "issues"
    assert processed_record.action == "objective_created"
    assert processed_record.project_id == project_id
    assert processed_record.issue_number == 11
    assert processed_record.reason == ""

    assert ignored_record is not None
    assert ignored_record.event == "issue_comment"
    assert ignored_record.action == "ignored"
    assert ignored_record.project_id is None
    assert ignored_record.issue_number == 12
    assert ignored_record.reason == "No supported command found"


def test_github_webhook_invalid_payload_marks_delivery_failed(
    client: tuple[TestClient, sessionmaker],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        "/webhooks/github",
        json={
            "action": "opened",
            "repository": {"full_name": "acme/invalid-payload-demo"},
        },
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-invalid-payload-failure",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid issues webhook payload"

    with session_factory() as db:
        delivery = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-invalid-payload-failure"
            )
        )
    assert delivery is not None
    assert delivery.event == "issues"
    assert delivery.action == "failed"
    assert delivery.reason == "Invalid issues webhook payload"

    metrics = test_client.get("/metrics")
    assert metrics.status_code == 200
    line = next(
        (raw for raw in metrics.text.splitlines() if raw.startswith("agent_hub_webhook_deliveries_failed_total ")),
        "",
    )
    assert line == "agent_hub_webhook_deliveries_failed_total 1"


def test_github_webhook_oversized_payload_marks_delivery_failed(
    client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session_factory = client
    monkeypatch.setenv("AGENT_HUB_GITHUB_WEBHOOK_MAX_PAYLOAD_BYTES", "1024")

    response = test_client.post(
        "/webhooks/github",
        json={
            "action": "opened",
            "repository": {"full_name": "acme/oversized-payload-demo"},
            "issue": {
                "number": 90,
                "title": "A very long payload title",
                "body": "x" * 2048,
            },
        },
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "delivery-oversized-payload-failure",
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Webhook payload exceeds max allowed size (1024 bytes)"

    with session_factory() as db:
        delivery = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-oversized-payload-failure"
            )
        )
    assert delivery is not None
    assert delivery.event == "issues"
    assert delivery.action == "failed"
    assert delivery.reason == "Webhook payload exceeds max allowed size (1024 bytes)"


def test_github_webhook_unexpected_handler_error_marks_delivery_failed(
    client: tuple[TestClient, sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, session_factory = client
    long_message = "handler failure " * 80

    def _raise_handler_failure(db, payload):  # noqa: ARG001
        raise RuntimeError(long_message)

    monkeypatch.setattr(github_webhooks, "_handle_issues_event", _raise_handler_failure)

    with pytest.raises(RuntimeError, match="handler failure"):
        test_client.post(
            "/webhooks/github",
            json={
                "action": "opened",
                "repository": {"full_name": "acme/unexpected-error-demo"},
                "issue": {"number": 25, "title": "Trigger crash"},
            },
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "delivery-unexpected-handler-failure",
            },
        )

    with session_factory() as db:
        delivery = db.scalar(
            select(models.GitHubWebhookDelivery).where(
                models.GitHubWebhookDelivery.delivery_id == "delivery-unexpected-handler-failure"
            )
        )
    assert delivery is not None
    assert delivery.event == "issues"
    assert delivery.action == "failed"
    assert delivery.reason.startswith("RuntimeError: handler failure")
    assert len(delivery.reason) <= 300
