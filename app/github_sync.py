from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_BASE_URL_ENV = "GITHUB_API_BASE_URL"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"


class GitHubSyncError(RuntimeError):
    """Base error for GitHub sync adapter failures."""


class GitHubAPIError(GitHubSyncError):
    """Raised when GitHub returns a non-success status code."""

    def __init__(self, *, method: str, url: str, status_code: int, detail: str) -> None:
        self.method = method.upper()
        self.url = url
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"GitHub API request failed [{self.status_code}] {self.method} {self.url}: {self.detail}"
        )


def parse_github_repo(repo_url: str) -> tuple[str, str]:
    """
    Parse a GitHub repository URL into (owner, repo).

    Supported formats:
    - https://github.com/<owner>/<repo>[.git]
    - git@github.com:<owner>/<repo>[.git]
    """

    value = repo_url.strip()
    if not value:
        raise ValueError("repo_url cannot be empty")

    if value.startswith("git@"):
        _, separator, path = value.partition(":")
        if not separator:
            raise ValueError(f"Unsupported git@ repository URL format: {repo_url}")
        path_parts = [segment for segment in path.strip("/").split("/") if segment]
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"}:
            raise ValueError(
                f"Unsupported repository URL scheme `{parsed.scheme}`; expected https:// or git@ URL"
            )
        path_parts = [segment for segment in parsed.path.strip("/").split("/") if segment]

    if len(path_parts) != 2:
        raise ValueError(f"Repository URL must point to owner/repo: {repo_url}")

    owner, repo = path_parts
    repo = repo.removesuffix(".git")
    if not owner or not repo:
        raise ValueError(f"Repository URL must point to owner/repo: {repo_url}")

    return owner, repo


class GitHubSyncAdapter:
    """Small httpx-based adapter for a subset of GitHub API calls."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base_url: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved_token = (token if token is not None else os.getenv(GITHUB_TOKEN_ENV, "")).strip()
        if not resolved_token:
            raise ValueError(f"Missing GitHub token. Set {GITHUB_TOKEN_ENV} or pass token=...")

        resolved_base_url = (
            api_base_url
            if api_base_url is not None
            else os.getenv(GITHUB_API_BASE_URL_ENV, DEFAULT_GITHUB_API_BASE_URL)
        ).strip()
        if not resolved_base_url:
            raise ValueError("GitHub API base URL cannot be empty")
        if not resolved_base_url.endswith("/"):
            resolved_base_url = f"{resolved_base_url}/"

        self._client = httpx.Client(
            base_url=resolved_base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {resolved_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubSyncAdapter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def create_pull_request(
        self,
        *,
        owner: str,
        repo: str,
        head: str,
        base: str,
        title: str,
        body: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"repos/{owner}/{repo}/pulls",
            {
                "head": head,
                "base": base,
                "title": title,
                "body": body,
            },
        )

    def create_issue_comment(
        self,
        *,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST",
            f"repos/{owner}/{repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    def set_commit_status(
        self,
        *,
        owner: str,
        repo: str,
        sha: str,
        state: str,
        context: str,
        description: str,
        target_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": state,
            "context": context,
            "description": description,
        }
        if target_url:
            payload["target_url"] = target_url

        return self._request_json("POST", f"repos/{owner}/{repo}/statuses/{sha}", payload)

    def _request_json(self, method: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.request(method, endpoint, json=payload)
        if not response.is_success:
            detail = _extract_error_detail(response)
            raise GitHubAPIError(
                method=method,
                url=str(response.request.url),
                status_code=response.status_code,
                detail=detail,
            )

        if not response.content:
            return {}
        return response.json()


def _extract_error_detail(response: httpx.Response) -> str:
    if not response.content:
        return "empty response body"

    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or "empty response body"

    if isinstance(payload, dict):
        message = str(payload.get("message", "")).strip()
        errors = payload.get("errors")
        if message and errors is not None:
            return f"{message}; errors={errors}"
        if message:
            return message

    return str(payload)
