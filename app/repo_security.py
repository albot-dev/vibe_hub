from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings


ALLOWED_REMOTE_SCHEMES = {"http", "https", "ssh", "git"}



def _is_bare_repo(path: Path) -> bool:
    return path.is_dir() and (path / "HEAD").exists() and (path / "objects").is_dir()



def _is_repo_path(path: Path) -> bool:
    return (path / ".git").exists() or _is_bare_repo(path)



def _is_within(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents



def normalize_and_validate_repo_url(repo_url: str, settings: Settings) -> str:
    value = repo_url.strip()
    if not value:
        raise ValueError("repo_url cannot be empty")

    if value.startswith("git@"):
        return value

    parsed = urlparse(value)
    if parsed.scheme in ALLOWED_REMOTE_SCHEMES:
        return value

    if parsed.scheme == "file":
        local_value = Path(parsed.path)
    else:
        local_value = Path(value).expanduser()

    if not settings.allow_local_repo_paths:
        raise ValueError("Local repository paths are disabled")

    resolved = local_value.resolve()
    if not resolved.exists():
        raise ValueError(f"Local repository path does not exist: {resolved}")
    if not _is_repo_path(resolved):
        raise ValueError(f"Path is not a git repository: {resolved}")

    if settings.allowed_local_repo_root:
        allowed_root = Path(settings.allowed_local_repo_root).expanduser().resolve()
        if not _is_within(allowed_root, resolved):
            raise ValueError(
                f"Local repository path `{resolved}` is outside allowed root `{allowed_root}`"
            )

    return str(resolved)
