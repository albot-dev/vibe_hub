from __future__ import annotations

import pytest

import app.main as app_main
from app.config import Settings


def _hardened_production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://agent_hub:password@postgres:5432/agent_hub",
        "require_api_key": True,
        "api_keys": "k1",
        "auth_require_roles": True,
        "auth_require_reads": True,
        "jwt_secret": "x" * 32,
        "allow_local_repo_paths": False,
        "github_webhook_secret": "webhook-secret",
        "metrics_require_token": True,
        "metrics_bearer_token": "metrics-token-abcdefghijklmnopqrstuvwxyz",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_safety_errors_empty_for_hardened_config() -> None:
    settings = _hardened_production_settings()
    assert settings.production_safety_errors() == []


def test_production_safety_errors_report_critical_misconfiguration() -> None:
    settings = _hardened_production_settings(
        database_url="sqlite:///./agent_hub.db",
        require_api_key=False,
        api_keys="",
        auth_require_roles=False,
        auth_require_reads=False,
        jwt_secret="short",
        allow_local_repo_paths=True,
        github_webhook_secret="",
        metrics_require_token=False,
        metrics_bearer_token="short",
    )

    errors = settings.production_safety_errors()

    assert any("AGENT_HUB_REQUIRE_API_KEY" in item for item in errors)
    assert any("AGENT_HUB_API_KEYS" in item for item in errors)
    assert any("AGENT_HUB_AUTH_REQUIRE_ROLES" in item for item in errors)
    assert any("AGENT_HUB_AUTH_REQUIRE_READS" in item for item in errors)
    assert any("AGENT_HUB_JWT_SECRET" in item for item in errors)
    assert any("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS" in item for item in errors)
    assert any("AGENT_HUB_GITHUB_WEBHOOK_SECRET" in item for item in errors)
    assert any("AGENT_HUB_METRICS_REQUIRE_TOKEN" in item for item in errors)
    assert any("AGENT_HUB_METRICS_BEARER_TOKEN" in item for item in errors)
    assert any("AGENT_HUB_DATABASE_URL" in item for item in errors)


def test_non_production_environment_does_not_enforce_production_guards() -> None:
    settings = Settings(
        app_env="development",
        require_api_key=False,
        auth_require_roles=False,
        allow_local_repo_paths=True,
        database_url="sqlite:///./agent_hub.db",
    )
    assert settings.production_safety_errors() == []


def test_runtime_configuration_guard_raises_on_unsafe_production() -> None:
    settings = _hardened_production_settings(require_api_key=False)
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        app_main._validate_runtime_configuration(settings)


def test_production_safety_errors_require_trusted_proxies_when_forwarded_headers_enabled() -> None:
    settings = _hardened_production_settings(
        rate_limit_trust_proxy_headers=True,
        trusted_proxy_ips="",
    )
    errors = settings.production_safety_errors()
    assert any("AGENT_HUB_TRUSTED_PROXY_IPS" in item for item in errors)
