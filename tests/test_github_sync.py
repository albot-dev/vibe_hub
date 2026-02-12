from __future__ import annotations

import json

import httpx
import pytest

from app.github_sync import GitHubAPIError, GitHubSyncAdapter, parse_github_repo


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        ("https://github.com/octo-org/octo-repo", ("octo-org", "octo-repo")),
        ("https://github.com/octo-org/octo-repo.git", ("octo-org", "octo-repo")),
        ("https://github.com/octo-org/octo-repo/", ("octo-org", "octo-repo")),
        ("git@github.com:octo-org/octo-repo", ("octo-org", "octo-repo")),
        ("git@github.com:octo-org/octo-repo.git", ("octo-org", "octo-repo")),
    ],
)
def test_parse_github_repo_success(repo_url: str, expected: tuple[str, str]) -> None:
    assert parse_github_repo(repo_url) == expected


@pytest.mark.parametrize(
    "repo_url",
    [
        "",
        "github.com/octo-org/octo-repo",
        "ssh://github.com/octo-org/octo-repo.git",
        "https://github.com/octo-org",
        "https://github.com/octo-org/octo-repo/pulls",
        "git@github.com:octo-org",
    ],
)
def test_parse_github_repo_invalid_url(repo_url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_repo(repo_url)


def test_create_pull_request_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/repos/acme/widgets/pulls"
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {
            "head": "feature/improve-ci",
            "base": "main",
            "title": "Improve CI behavior",
            "body": "This updates CI retries.",
        }
        return httpx.Response(201, json={"number": 12, "state": "open"})

    transport = httpx.MockTransport(handler)
    with GitHubSyncAdapter(
        token="test-token",
        api_base_url="https://api.github.test",
        transport=transport,
    ) as adapter:
        result = adapter.create_pull_request(
            owner="acme",
            repo="widgets",
            head="feature/improve-ci",
            base="main",
            title="Improve CI behavior",
            body="This updates CI retries.",
        )
    assert result["number"] == 12


def test_create_issue_comment_uses_env_token_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "from-env-token")
    monkeypatch.setenv("GITHUB_API_BASE_URL", "https://ghe.example/api/v3")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://ghe.example/api/v3/repos/acme/widgets/issues/42/comments"
        assert request.headers["Authorization"] == "Bearer from-env-token"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {"body": "Looks good to me."}
        return httpx.Response(201, json={"id": 1001})

    transport = httpx.MockTransport(handler)
    with GitHubSyncAdapter(transport=transport) as adapter:
        result = adapter.create_issue_comment(
            owner="acme",
            repo="widgets",
            issue_number=42,
            body="Looks good to me.",
        )
    assert result["id"] == 1001


def test_set_commit_status_success_without_target_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/repos/acme/widgets/statuses/abc123"
        body = json.loads(request.content.decode("utf-8"))
        assert body == {
            "state": "success",
            "context": "ci/build",
            "description": "Build passed",
        }
        return httpx.Response(201, json={"state": "success"})

    transport = httpx.MockTransport(handler)
    with GitHubSyncAdapter(
        token="test-token",
        api_base_url="https://api.github.test",
        transport=transport,
    ) as adapter:
        result = adapter.set_commit_status(
            owner="acme",
            repo="widgets",
            sha="abc123",
            state="success",
            context="ci/build",
            description="Build passed",
        )
    assert result["state"] == "success"


def test_non_2xx_response_raises_error_with_context() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"message": "Validation Failed", "errors": [{"field": "head"}]},
        )

    transport = httpx.MockTransport(handler)
    with GitHubSyncAdapter(
        token="test-token",
        api_base_url="https://api.github.test",
        transport=transport,
    ) as adapter:
        with pytest.raises(GitHubAPIError) as error:
            adapter.create_pull_request(
                owner="acme",
                repo="widgets",
                head="bad-branch",
                base="main",
                title="Broken PR",
                body="This should fail.",
            )

    text = str(error.value)
    assert "422" in text
    assert "POST" in text
    assert "/repos/acme/widgets/pulls" in text
    assert "Validation Failed" in text
