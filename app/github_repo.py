from __future__ import annotations

from urllib.parse import urlparse


def canonical_repo_identity(owner: str, repo: str) -> tuple[str, str]:
    return owner.strip().lower(), repo.strip().removesuffix(".git").lower()


def parse_github_repo_url(repo_url: str) -> tuple[str, str]:
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


def extract_owner_repo(value: str | None) -> tuple[str, str] | None:
    raw = (value or "").strip()
    if not raw:
        return None

    try:
        owner, repo = parse_github_repo_url(raw)
    except ValueError:
        parsed = urlparse(raw)
        host = parsed.netloc.strip().lower()
        parts = [segment for segment in parsed.path.strip("/").split("/") if segment]
        if host != "api.github.com" or len(parts) < 3 or parts[0].lower() != "repos":
            return None
        owner, repo = parts[1], parts[2]

    owner = owner.strip()
    repo = repo.strip().removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


def normalize_repo_locator(value: str | None) -> str:
    normalized = (value or "").strip().lower().rstrip("/")
    return normalized.removesuffix(".git")

