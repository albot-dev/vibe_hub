from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_large_files.sh"


def _run(cmd: list[str], cwd: Path) -> str:
    proc = subprocess.run(cmd, cwd=cwd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"Command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.name", "Test Bot"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.local"], cwd=repo)
    return repo


def test_check_large_files_script_passes_for_small_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "small.txt").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "small.txt"], cwd=repo)

    env = os.environ.copy()
    env["LARGE_FILE_LIMIT_MB"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "no tracked files exceed" in result.stdout


def test_check_large_files_script_fails_for_oversized_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "large.bin").write_bytes(b"x" * (2 * 1024 * 1024))
    _run(["git", "add", "large.bin"], cwd=repo)

    env = os.environ.copy()
    env["LARGE_FILE_LIMIT_MB"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "large.bin" in result.stderr

