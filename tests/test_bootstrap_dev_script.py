from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "bootstrap_dev.sh"


def _run_script(*, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT_PATH)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_bootstrap_dev_script_fails_with_help_when_uv_missing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["HOME"] = str(tmp_path)
    env.pop("INSTALL_UV", None)

    result = _run_script(env=env)

    assert result.returncode != 0
    assert "uv is not installed" in result.stderr
    assert "INSTALL_UV=1 bash scripts/bootstrap_dev.sh" in result.stderr


def test_bootstrap_dev_script_runs_uv_sync_when_uv_exists(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    args_log = tmp_path / "uv_args.log"
    uv_path = bin_dir / "uv"
    uv_path.write_text(
        "#!/bin/bash\n"
        "echo \"$*\" >> \"$UV_ARGS_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HOME"] = str(tmp_path)
    env["UV_ARGS_LOG"] = str(args_log)
    env.pop("INSTALL_UV", None)

    result = _run_script(env=env)

    assert result.returncode == 0, result.stderr
    assert "bootstrap complete" in result.stdout
    assert args_log.exists()
    assert "sync --extra dev" in args_log.read_text(encoding="utf-8")
