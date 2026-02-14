from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "verify_image_signature.sh"


def _write_env_file(tmp_path: Path) -> Path:
    env_path = tmp_path / "verify.env"
    env_path.write_text(
        "\n".join(
            [
                "AGENT_HUB_IMAGE=ghcr.io/example/vibe_hub@sha256:" + ("c" * 64),
                "AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX="
                "^https://github[.]com/example/vibe_hub/[.]github/workflows/image[.]yml@refs/(heads/main|tags/v.*)$",
                "AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER=https://token.actions.githubusercontent.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return env_path


def _run_script(env_path: Path, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), str(env_path)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_verify_image_signature_uses_existing_cosign_binary(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    args_log = tmp_path / "cosign_args.log"

    cosign_path = bin_dir / "cosign"
    cosign_path.write_text(
        "#!/bin/bash\n"
        "echo \"$*\" >> \"$COSIGN_ARGS_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    cosign_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["COSIGN_AUTO_INSTALL"] = "0"
    env["COSIGN_ARGS_LOG"] = str(args_log)

    result = _run_script(env_path, env=env)

    assert result.returncode == 0, result.stderr
    assert "signature verification passed" in result.stdout
    args = args_log.read_text(encoding="utf-8")
    assert "verify" in args
    assert "--certificate-identity-regexp" in args
    assert "--certificate-oidc-issuer" in args
    assert "ghcr.io/example/vibe_hub@sha256:" in args


def test_verify_image_signature_fails_when_cosign_missing_and_auto_install_disabled(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path)

    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["COSIGN_AUTO_INSTALL"] = "0"

    result = _run_script(env_path, env=env)

    assert result.returncode != 0
    assert "cosign is not installed or not in PATH" in result.stderr
    assert "COSIGN_AUTO_INSTALL=1" in result.stderr


def test_verify_image_signature_bootstraps_cosign_with_helper(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path)
    install_dir = tmp_path / "tools-bin"
    helper_log = tmp_path / "helper.log"
    args_log = tmp_path / "cosign_args.log"
    helper_path = tmp_path / "install_cosign_helper.sh"

    helper_path.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "mkdir -p \"$COSIGN_INSTALL_DIR\"\n"
        "cat > \"$COSIGN_INSTALL_DIR/cosign\" <<'EOS'\n"
        "#!/bin/bash\n"
        "echo \"$*\" >> \"$COSIGN_ARGS_LOG\"\n"
        "exit 0\n"
        "EOS\n"
        "chmod 755 \"$COSIGN_INSTALL_DIR/cosign\"\n"
        "echo helper-ran > \"$COSIGN_HELPER_LOG\"\n",
        encoding="utf-8",
    )
    helper_path.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = "/usr/bin:/bin"
    env["COSIGN_AUTO_INSTALL"] = "1"
    env["COSIGN_INSTALL_DIR"] = str(install_dir)
    env["COSIGN_INSTALL_HELPER"] = str(helper_path)
    env["COSIGN_HELPER_LOG"] = str(helper_log)
    env["COSIGN_ARGS_LOG"] = str(args_log)

    result = _run_script(env_path, env=env)

    assert result.returncode == 0, result.stderr
    assert helper_log.exists()
    assert "signature verification passed" in result.stdout
    assert "verify" in args_log.read_text(encoding="utf-8")
