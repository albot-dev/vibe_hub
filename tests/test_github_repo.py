from __future__ import annotations

import pytest

from app.github_repo import (
    canonical_repo_identity,
    extract_owner_repo,
    normalize_repo_locator,
    parse_github_repo_url,
)


@pytest.mark.parametrize(
    ("repo_url", "expected"),
    [
        ("https://github.com/octo-org/octo-repo", ("octo-org", "octo-repo")),
        ("https://github.com/octo-org/octo-repo.git", ("octo-org", "octo-repo")),
        ("git@github.com:octo-org/octo-repo", ("octo-org", "octo-repo")),
        ("git@github.com:octo-org/octo-repo.git", ("octo-org", "octo-repo")),
    ],
)
def test_parse_github_repo_url_success(repo_url: str, expected: tuple[str, str]) -> None:
    assert parse_github_repo_url(repo_url) == expected


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
def test_parse_github_repo_url_invalid(repo_url: str) -> None:
    with pytest.raises(ValueError):
        parse_github_repo_url(repo_url)


def test_extract_owner_repo_supports_api_repo_url() -> None:
    assert extract_owner_repo("https://api.github.com/repos/Acme/Widget") == ("Acme", "Widget")
    assert extract_owner_repo("https://api.github.com/repos/Acme/Widget/issues/1") == ("Acme", "Widget")


def test_extract_owner_repo_handles_non_api_values() -> None:
    assert extract_owner_repo("") is None
    assert extract_owner_repo("https://example.com/acme/widget") == ("acme", "widget")
    assert extract_owner_repo("https://example.com/acme") is None


def test_canonical_repo_identity_and_normalize_repo_locator() -> None:
    assert canonical_repo_identity("Acme", "Widget.git") == ("acme", "widget")
    assert normalize_repo_locator("https://github.com/Acme/Widget.git/") == "https://github.com/acme/widget"
