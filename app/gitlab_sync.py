from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlparse

import httpx


DEFAULT_GITLAB_API_BASE_URL = "https://gitlab.com/api/v4"
GITLAB_API_BASE_URL_ENV = "GITLAB_API_BASE_URL"
GITLAB_TOKEN_ENV = "GITLAB_TOKEN"


class GitLabSyncError(RuntimeError):
    """Base error for GitLab sync adapter failures."""


class GitLabAPIError(GitLabSyncError):
    """Raised when GitLab returns a non-success status code."""

    def __init__(self, *, method: str, url: str, status_code: int, detail: str) -> None:
        self.method = method.upper()
        self.url = url
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"GitLab API request failed [{self.status_code}] {self.method} {self.url}: {self.detail}"
        )


def parse_gitlab_repo(repo_url: str) -> str:
    """
    Parse a GitLab repository URL into a project path.

    Supported formats:
    - https://<host>/<group>/<project>[.git]
    - git@<host>:<group>/<project>[.git]
    """

    value = repo_url.strip()
    if not value:
        raise ValueError("repo_url cannot be empty")

    if value.startswith("git@"):
        _, at_separator, host_and_path = value.partition("@")
        host, colon_separator, path = host_and_path.partition(":")
        if not at_separator or not colon_separator or not host.strip():
            raise ValueError(f"Unsupported git@ repository URL format: {repo_url}")
        path_parts = [segment for segment in path.strip("/").split("/") if segment]
    else:
        parsed = urlparse(value)
        if parsed.scheme not in {"https", "http"}:
            raise ValueError(
                f"Unsupported repository URL scheme `{parsed.scheme}`; expected https:// or git@ URL"
            )
        if not parsed.netloc.strip():
            raise ValueError(f"Repository URL host is missing: {repo_url}")
        # GitLab web URLs for resources append "/-/..." (for example merge requests/issues).
        # Keep only the repository path prefix so users can paste either repo URL or resource URL.
        path = parsed.path.strip("/")
        path = path.split("/-/", 1)[0]
        path_parts = [segment for segment in path.split("/") if segment]

    if len(path_parts) < 2:
        raise ValueError(f"Repository URL must include group/project path: {repo_url}")

    path_parts[-1] = path_parts[-1].removesuffix(".git")
    if not all(path_parts):
        raise ValueError(f"Repository URL must include group/project path: {repo_url}")
    return "/".join(path_parts)


def _encode_project_path(project_path: str) -> str:
    return quote(project_path.strip(), safe="")


class GitLabSyncAdapter:
    """Small httpx-based adapter for a subset of GitLab API calls."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base_url: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        resolved_token = (token if token is not None else os.getenv(GITLAB_TOKEN_ENV, "")).strip()
        if not resolved_token:
            raise ValueError(f"Missing GitLab token. Set {GITLAB_TOKEN_ENV} or pass token=...")

        resolved_base_url = (
            api_base_url
            if api_base_url is not None
            else os.getenv(GITLAB_API_BASE_URL_ENV, DEFAULT_GITLAB_API_BASE_URL)
        ).strip()
        if not resolved_base_url:
            raise ValueError("GitLab API base URL cannot be empty")
        if not resolved_base_url.endswith("/"):
            resolved_base_url = f"{resolved_base_url}/"

        self._client = httpx.Client(
            base_url=resolved_base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "PRIVATE-TOKEN": resolved_token,
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitLabSyncAdapter":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def create_merge_request(
        self,
        *,
        project_path: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        encoded = _encode_project_path(project_path)
        return self._request_json(
            "POST",
            f"projects/{encoded}/merge_requests",
            {
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            },
        )

    def create_issue_note(
        self,
        *,
        project_path: str,
        issue_iid: int,
        body: str,
    ) -> dict[str, Any]:
        encoded = _encode_project_path(project_path)
        return self._request_json(
            "POST",
            f"projects/{encoded}/issues/{issue_iid}/notes",
            {"body": body},
        )

    def set_commit_status(
        self,
        *,
        project_path: str,
        sha: str,
        state: str,
        context: str,
        description: str,
        target_url: str | None = None,
    ) -> dict[str, Any]:
        encoded = _encode_project_path(project_path)
        payload: dict[str, Any] = {
            "state": state,
            "name": context,
            "description": description,
        }
        if target_url:
            payload["target_url"] = target_url
        return self._request_json(
            "POST",
            f"projects/{encoded}/statuses/{sha}",
            payload,
        )

    def _request_json(self, method: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.request(method, endpoint, json=payload)
        if not response.is_success:
            detail = _extract_error_detail(response)
            raise GitLabAPIError(
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
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        if message is not None:
            return str(message)

    return str(payload)
