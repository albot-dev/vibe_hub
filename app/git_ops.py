from __future__ import annotations

import fcntl
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.providers import CodeChange


class GitError(RuntimeError):
    pass


@dataclass(slots=True)
class GitExecutionResult:
    branch_name: str
    commit_sha: str
    diff: str
    workspace_path: Path


class GitWorkspaceManager:
    def __init__(
        self,
        *,
        project_id: int,
        repo_url: str,
        default_branch: str,
        workspace_root: Path | None = None,
        command_timeout_sec: int | None = None,
        command_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        root = workspace_root or Path(os.getenv("AGENT_HUB_WORKSPACES", ".agent_workspaces"))
        self.workspace_root = root.resolve()
        self.workspace_path = (self.workspace_root / f"project-{project_id}").resolve()
        self.lock_path = self.workspace_root / f"project-{project_id}.lock"
        self.repo_url = repo_url
        self.default_branch = default_branch
        self.command_timeout_sec = command_timeout_sec or settings.git_command_timeout_sec
        self.command_retries = command_retries if command_retries is not None else settings.git_command_retries

    def _is_transient_error(self, output: str) -> bool:
        text = output.lower()
        return any(
            marker in text
            for marker in (
                "index.lock",
                "another git process seems to be running",
                "unable to access",
                "failed to connect",
                "connection reset",
                "operation timed out",
            )
        )

    def _run(self, cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
        attempts = max(self.command_retries + 1, 1)
        last_error: str | None = None

        for attempt in range(1, attempts + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=cwd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.command_timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                last_error = f"Command timed out after {self.command_timeout_sec}s: {' '.join(cmd)}"
                if attempt < attempts:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
                    continue
                raise GitError(last_error) from exc

            if not check or proc.returncode == 0:
                return proc

            stderr = proc.stderr.strip()
            stdout = proc.stdout.strip()
            output = stderr or stdout or "no output"
            last_error = f"Command failed: {' '.join(cmd)}\n{output}"

            if attempt < attempts and self._is_transient_error(output):
                time.sleep(0.2 * (2 ** (attempt - 1)))
                continue
            raise GitError(last_error)

        raise GitError(last_error or f"Command failed: {' '.join(cmd)}")

    def _run_git(self, args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self._run(["git", *args], cwd=cwd or self.workspace_path, check=check)

    @contextmanager
    def _project_lock(self):
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _normalized_repo_url(self) -> str:
        if self.repo_url.startswith(("http://", "https://", "ssh://", "git@", "file://")):
            return self.repo_url
        path = Path(self.repo_url).expanduser()
        if path.exists():
            return str(path.resolve())
        return self.repo_url

    def _configure_identity(self) -> None:
        self._run_git(["config", "user.name", "Agent Hub Bot"])
        self._run_git(["config", "user.email", "agent-hub@example.local"])

    def _prepare_workspace_locked(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        if not self.workspace_path.exists():
            source = self._normalized_repo_url()
            self._run_git(
                ["clone", source, str(self.workspace_path)],
                cwd=self.workspace_root,
            )
        elif not (self.workspace_path / ".git").exists():
            raise GitError(f"Workspace exists but is not a git repository: {self.workspace_path}")

        self._configure_identity()
        self._run_git(["fetch", "--all", "--prune"], check=False)

        checkout = self._run_git(["checkout", self.default_branch], check=False)
        if checkout.returncode != 0:
            self._run_git(["checkout", "-b", self.default_branch, f"origin/{self.default_branch}"])

        self._run_git(["pull", "--ff-only", "origin", self.default_branch], check=False)
        return self.workspace_path

    def prepare_workspace(self) -> Path:
        with self._project_lock():
            return self._prepare_workspace_locked()

    def _ensure_path_within_workspace(self, relative_path: str) -> Path:
        target = (self.workspace_path / relative_path).resolve()
        workspace = self.workspace_path.resolve()
        if workspace not in target.parents and target != workspace:
            raise GitError(f"Refusing to write outside workspace: {relative_path}")
        return target

    def commit_agent_change(self, *, branch_name: str, change: CodeChange) -> GitExecutionResult:
        with self._project_lock():
            self._prepare_workspace_locked()
            self._run_git(["checkout", self.default_branch])
            self._run_git(["branch", "-D", branch_name], check=False)
            self._run_git(["checkout", "-b", branch_name])

            target = self._ensure_path_within_workspace(change.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = change.content if change.content.endswith("\n") else f"{change.content}\n"
            target.write_text(content, encoding="utf-8")

            self._run_git(["add", change.relative_path])
            commit_proc = self._run_git(["commit", "-m", change.commit_message], check=False)
            if commit_proc.returncode != 0:
                output = "\n".join(part for part in [commit_proc.stdout.strip(), commit_proc.stderr.strip()] if part)
                if "nothing to commit" not in output.lower():
                    raise GitError(f"Commit failed for branch {branch_name}: {output}")

            commit_sha = self._run_git(["rev-parse", "HEAD"]).stdout.strip()
            diff = self._run_git(["show", "--format=", "--no-color", "HEAD"]).stdout
            return GitExecutionResult(
                branch_name=branch_name,
                commit_sha=commit_sha,
                diff=diff,
                workspace_path=self.workspace_path,
            )

    def merge_branch(self, *, branch_name: str) -> str:
        with self._project_lock():
            self._prepare_workspace_locked()
            self._run_git(["checkout", self.default_branch])
            ff_merge = self._run_git(["merge", "--ff-only", branch_name], check=False)
            if ff_merge.returncode != 0:
                self._run_git(["merge", "--no-ff", "-m", f"Merge {branch_name} [agent]", branch_name])

            if os.getenv("AGENT_HUB_AUTO_PUSH", "0").strip().lower() in {"1", "true", "yes"}:
                self._run_git(["push", "origin", branch_name], check=True)
                self._run_git(["push", "origin", self.default_branch], check=True)

            return self._run_git(["rev-parse", "HEAD"]).stdout.strip()
