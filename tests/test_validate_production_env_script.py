from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = PROJECT_ROOT / "scripts" / "validate_production_env.sh"


def _write_env_file(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "POSTGRES_IMAGE": "postgres:16-alpine@sha256:" + "a" * 64,
        "PROMETHEUS_IMAGE": "prom/prometheus:v2.54.1@sha256:" + "b" * 64,
        "POSTGRES_DB": "agent_hub",
        "POSTGRES_USER": "agent_hub",
        "POSTGRES_PASSWORD": "supersecuredbpassword",
        "AGENT_HUB_IMAGE": "ghcr.io/example/vibe_hub@sha256:" + "c" * 64,
        "AGENT_HUB_COSIGN_CERTIFICATE_IDENTITY_REGEX": "^https://github[.]com/example/vibe_hub/[.]github/workflows/image[.]yml@refs/(heads/main|tags/v.*)$",
        "AGENT_HUB_COSIGN_CERTIFICATE_OIDC_ISSUER": "https://token.actions.githubusercontent.com",
        "AGENT_HUB_APP_ENV": "production",
        "AGENT_HUB_DATABASE_URL": "postgresql+psycopg://agent_hub:supersecuredbpassword@postgres:5432/agent_hub",
        "AGENT_HUB_REQUIRE_API_KEY": "1",
        "AGENT_HUB_API_KEYS": "top-secret-agent-key",
        "AGENT_HUB_AUTH_REQUIRE_ROLES": "1",
        "AGENT_HUB_AUTH_REQUIRE_READS": "1",
        "AGENT_HUB_JWT_SECRET": "abcdefghijklmnopqrstuvwxyz123456",
        "AGENT_HUB_ALLOW_LOCAL_REPO_PATHS": "0",
        "AGENT_HUB_GITHUB_WEBHOOK_SECRET": "top-secret-webhook",
        "AGENT_HUB_METRICS_REQUIRE_TOKEN": "1",
        "AGENT_HUB_METRICS_BEARER_TOKEN": "metrics-token-abcdefghijklmnopqrstuvwxyz",
        "AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS": "0",
    }
    values.update(overrides)

    env_path = tmp_path / "production.env"
    env_path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return env_path


def _run_validator(env_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VALIDATOR), str(env_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_production_env_passes_for_hardened_config(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path)
    result = _run_validator(env_path)
    assert result.returncode == 0, result.stderr
    assert "validation passed" in result.stdout


def test_validate_production_env_fails_without_webhook_secret(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path, AGENT_HUB_GITHUB_WEBHOOK_SECRET="")
    result = _run_validator(env_path)
    assert result.returncode != 0
    assert "AGENT_HUB_GITHUB_WEBHOOK_SECRET" in result.stderr


def test_validate_production_env_fails_without_metrics_token(tmp_path: Path) -> None:
    env_path = _write_env_file(tmp_path, AGENT_HUB_METRICS_BEARER_TOKEN="")
    result = _run_validator(env_path)
    assert result.returncode != 0
    assert "AGENT_HUB_METRICS_BEARER_TOKEN" in result.stderr


def test_validate_production_env_requires_trusted_proxies_when_forwarded_headers_enabled(tmp_path: Path) -> None:
    env_path = _write_env_file(
        tmp_path,
        AGENT_HUB_RATE_LIMIT_TRUST_PROXY_HEADERS="1",
        AGENT_HUB_TRUSTED_PROXY_IPS="",
    )
    result = _run_validator(env_path)
    assert result.returncode != 0
    assert "AGENT_HUB_TRUSTED_PROXY_IPS" in result.stderr
