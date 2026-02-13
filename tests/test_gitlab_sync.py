from __future__ import annotations

import json

import httpx
import pytest

from app.gitlab_sync import GitLabAPIError, GitLabSyncAdapter, parse_gitlab_repo


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        ("https://gitlab.com/acme/widgets", "acme/widgets"),
        ("https://gitlab.com/acme/widgets.git", "acme/widgets"),
        ("https://gitlab.com/acme/platform/widgets", "acme/platform/widgets"),
        (
            "https://gitlab.com/acme/platform/widgets/-/merge_requests/42",
            "acme/platform/widgets",
        ),
        (
            "https://gitlab.com/acme/platform/widgets/-/issues/11",
            "acme/platform/widgets",
        ),
        ("git@gitlab.com:acme/widgets.git", "acme/widgets"),
        ("git@gitlab.com:acme/platform/widgets", "acme/platform/widgets"),
    ],
)
def test_parse_gitlab_repo_success(repo_url: str, expected: str) -> None:
    assert parse_gitlab_repo(repo_url) == expected


@pytest.mark.parametrize(
    "repo_url",
    [
        "",
        "gitlab.com/acme/widgets",
        "ssh://gitlab.com/acme/widgets.git",
        "https://gitlab.com/acme",
        "git@gitlab.com:acme",
    ],
)
def test_parse_gitlab_repo_invalid_url(repo_url: str) -> None:
    with pytest.raises(ValueError):
        parse_gitlab_repo(repo_url)


def test_create_merge_request_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://gitlab.example/api/v4/projects/acme%2Fplatform%2Fwidgets/merge_requests"
        assert request.headers["PRIVATE-TOKEN"] == "test-token"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {
            "source_branch": "agent/42-feature",
            "target_branch": "main",
            "title": "Add feature",
            "description": "Feature implementation",
        }
        return httpx.Response(201, json={"iid": 42, "web_url": "https://gitlab.com/acme/platform/widgets/-/merge_requests/42"})

    transport = httpx.MockTransport(handler)
    with GitLabSyncAdapter(
        token="test-token",
        api_base_url="https://gitlab.example/api/v4",
        transport=transport,
    ) as adapter:
        result = adapter.create_merge_request(
            project_path="acme/platform/widgets",
            source_branch="agent/42-feature",
            target_branch="main",
            title="Add feature",
            description="Feature implementation",
        )
    assert result["iid"] == 42


def test_create_issue_note_uses_env_token_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITLAB_TOKEN", "env-token")
    monkeypatch.setenv("GITLAB_API_BASE_URL", "https://gitlab.internal/api/v4")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://gitlab.internal/api/v4/projects/acme%2Fwidgets/issues/17/notes"
        assert request.headers["PRIVATE-TOKEN"] == "env-token"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {"body": "Triggered by Agent Hub"}
        return httpx.Response(201, json={"id": 9001})

    transport = httpx.MockTransport(handler)
    with GitLabSyncAdapter(transport=transport) as adapter:
        result = adapter.create_issue_note(
            project_path="acme/widgets",
            issue_iid=17,
            body="Triggered by Agent Hub",
        )
    assert result["id"] == 9001


def test_set_commit_status_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://gitlab.example/api/v4/projects/acme%2Fwidgets/statuses/abc123"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {
            "state": "pending",
            "name": "agent-hub/sync",
            "description": "Sync pending",
            "target_url": "https://agent-hub.local/pr/1",
        }
        return httpx.Response(201, json={"status": "pending"})

    transport = httpx.MockTransport(handler)
    with GitLabSyncAdapter(
        token="test-token",
        api_base_url="https://gitlab.example/api/v4",
        transport=transport,
    ) as adapter:
        result = adapter.set_commit_status(
            project_path="acme/widgets",
            sha="abc123",
            state="pending",
            context="agent-hub/sync",
            description="Sync pending",
            target_url="https://agent-hub.local/pr/1",
        )
    assert result["status"] == "pending"


def test_non_2xx_response_raises_error_with_context() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Project Not Found"})

    transport = httpx.MockTransport(handler)
    with GitLabSyncAdapter(
        token="test-token",
        api_base_url="https://gitlab.example/api/v4",
        transport=transport,
    ) as adapter:
        with pytest.raises(GitLabAPIError) as error:
            adapter.create_merge_request(
                project_path="acme/missing",
                source_branch="feature/x",
                target_branch="main",
                title="Missing project",
                description="No project",
            )

    text = str(error.value)
    assert "404" in text
    assert "POST" in text
    assert "/projects/acme%2Fmissing/merge_requests" in text
    assert "Project Not Found" in text
