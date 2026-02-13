from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.git_ops import GitError, GitWorkspaceManager
from app.providers import CodeChange, FileChange


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _seed_remote_repo(tmp_path: Path) -> str:
    remote_path = tmp_path / "remote.git"
    seed_path = tmp_path / "seed_repo"
    seed_path.mkdir(parents=True, exist_ok=True)

    _run(["git", "init", "--bare", str(remote_path)], cwd=tmp_path)
    _run(["git", "init", "-b", "main"], cwd=seed_path)
    _run(["git", "config", "user.name", "Test Bot"], cwd=seed_path)
    _run(["git", "config", "user.email", "test@example.local"], cwd=seed_path)
    (seed_path / "README.md").write_text("# Seed Repo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed_path)
    _run(["git", "commit", "-m", "chore: seed"], cwd=seed_path)
    _run(["git", "remote", "add", "origin", str(remote_path)], cwd=seed_path)
    _run(["git", "push", "-u", "origin", "main"], cwd=seed_path)
    return str(remote_path)


def test_commit_agent_change_supports_multiple_file_changes(tmp_path: Path) -> None:
    repo_url = _seed_remote_repo(tmp_path)
    manager = GitWorkspaceManager(
        project_id=1,
        repo_url=repo_url,
        default_branch="main",
        workspace_root=tmp_path / "workspaces",
    )

    change = CodeChange(
        file_changes=[
            FileChange(path="src/feature.py", content="def run() -> str:\n    return 'ok'\n"),
            FileChange(path="tests/test_feature.py", content="def test_run_smoke() -> None:\n    assert True\n"),
        ],
        commit_message="feat: add generated feature scaffolding",
        summary="Adds source and test scaffolding.",
    )

    result = manager.commit_agent_change(branch_name="agent/multi-file", change=change)

    assert result.commit_sha
    assert (result.workspace_path / "src" / "feature.py").exists()
    assert (result.workspace_path / "tests" / "test_feature.py").exists()
    assert "src/feature.py" in result.diff
    assert "tests/test_feature.py" in result.diff


def test_commit_agent_change_rejects_path_escape_file_change(tmp_path: Path) -> None:
    repo_url = _seed_remote_repo(tmp_path)
    manager = GitWorkspaceManager(
        project_id=2,
        repo_url=repo_url,
        default_branch="main",
        workspace_root=tmp_path / "workspaces",
    )

    change = CodeChange(
        file_changes=[FileChange(path="../../outside.txt", content="unsafe\n")],
        commit_message="feat: unsafe",
        summary="unsafe",
    )

    with pytest.raises(GitError, match="Refusing to write outside workspace"):
        manager.commit_agent_change(branch_name="agent/unsafe-path", change=change)


def test_commit_agent_change_supports_patch_application(tmp_path: Path) -> None:
    repo_url = _seed_remote_repo(tmp_path)
    manager = GitWorkspaceManager(
        project_id=3,
        repo_url=repo_url,
        default_branch="main",
        workspace_root=tmp_path / "workspaces",
    )

    patch = "\n".join(
        [
            "diff --git a/patch_added.txt b/patch_added.txt",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/patch_added.txt",
            "@@ -0,0 +1 @@",
            "+hello from patch",
            "",
        ]
    )
    change = CodeChange(
        file_changes=[],
        patch=patch,
        commit_message="feat: apply unified diff patch",
        summary="apply patch",
    )

    result = manager.commit_agent_change(branch_name="agent/patch-apply", change=change)

    assert (result.workspace_path / "patch_added.txt").read_text(encoding="utf-8").strip() == "hello from patch"
    assert "patch_added.txt" in result.diff


def test_commit_agent_change_rejects_unsafe_patch_paths(tmp_path: Path) -> None:
    repo_url = _seed_remote_repo(tmp_path)
    manager = GitWorkspaceManager(
        project_id=4,
        repo_url=repo_url,
        default_branch="main",
        workspace_root=tmp_path / "workspaces",
    )

    patch = "\n".join(
        [
            "diff --git a/../../outside.txt b/../../outside.txt",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/../../outside.txt",
            "@@ -0,0 +1 @@",
            "+unsafe patch",
            "",
        ]
    )
    change = CodeChange(
        file_changes=[],
        patch=patch,
        commit_message="feat: reject unsafe patch",
        summary="reject unsafe patch",
    )

    with pytest.raises(GitError):
        manager.commit_agent_change(branch_name="agent/unsafe-patch", change=change)
