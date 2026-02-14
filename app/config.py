from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_HUB_", case_sensitive=False, extra="ignore")

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(default="sqlite:///./agent_hub.db")

    require_api_key: bool = Field(default=False)
    api_keys: str = Field(default="")
    auth_require_roles: bool = Field(default=False)
    auth_require_reads: bool = Field(default=False)
    jwt_secret: str = Field(default="")

    rate_limit_enabled: bool = Field(default=False)
    rate_limit_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    rate_limit_trust_proxy_headers: bool = Field(default=False)
    trusted_proxy_ips: str = Field(default="")

    default_page_size: int = Field(default=50, ge=1, le=500)
    max_page_size: int = Field(default=200, ge=1, le=2000)

    allow_local_repo_paths: bool = Field(default=True)
    allowed_local_repo_root: str | None = Field(default=None)

    git_command_timeout_sec: int = Field(default=60, ge=5, le=600)
    git_command_retries: int = Field(default=1, ge=0, le=10)

    job_worker_enabled: bool = Field(default=True)
    job_worker_poll_interval_sec: float = Field(default=1.0, ge=0.1, le=60.0)
    job_stale_timeout_sec: float = Field(default=900.0, ge=1.0, le=86400.0)
    require_test_cmd: bool = Field(default=False)

    github_webhook_secret: str = Field(default="")
    github_webhook_auto_enqueue: bool = Field(default=False)
    github_webhook_max_payload_bytes: int = Field(default=1_000_000, ge=1024, le=20_000_000)
    metrics_require_token: bool = Field(default=False)
    metrics_bearer_token: str = Field(default="")
    ui_env_prefill_enabled: bool = Field(default=False)

    def parsed_api_keys(self) -> set[str]:
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}

    def parsed_trusted_proxy_ips(self) -> set[str]:
        return {value.strip() for value in self.trusted_proxy_ips.split(",") if value.strip()}

    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @staticmethod
    def _contains_placeholder(value: str) -> bool:
        return "replace-with" in value.strip().lower()

    def production_safety_errors(self) -> list[str]:
        if not self.is_production():
            return []

        errors: list[str] = []

        if not self.require_api_key:
            errors.append("AGENT_HUB_REQUIRE_API_KEY must be enabled in production")

        if not self.parsed_api_keys():
            errors.append("AGENT_HUB_API_KEYS must be configured in production")

        if not self.auth_require_roles:
            errors.append("AGENT_HUB_AUTH_REQUIRE_ROLES must be enabled in production")

        if not self.auth_require_reads:
            errors.append("AGENT_HUB_AUTH_REQUIRE_READS must be enabled in production")

        if len(self.jwt_secret.strip()) < 32:
            errors.append("AGENT_HUB_JWT_SECRET must be at least 32 characters in production")

        if self.allow_local_repo_paths:
            errors.append("AGENT_HUB_ALLOW_LOCAL_REPO_PATHS must be disabled in production")

        if not self.github_webhook_secret.strip():
            errors.append("AGENT_HUB_GITHUB_WEBHOOK_SECRET must be configured in production")

        if not self.metrics_require_token:
            errors.append("AGENT_HUB_METRICS_REQUIRE_TOKEN must be enabled in production")

        if len(self.metrics_bearer_token.strip()) < 24:
            errors.append("AGENT_HUB_METRICS_BEARER_TOKEN must be at least 24 characters in production")

        if self.database_url.strip().lower().startswith("sqlite"):
            errors.append("AGENT_HUB_DATABASE_URL must not use sqlite in production")

        if not self.require_test_cmd:
            errors.append("AGENT_HUB_REQUIRE_TEST_CMD must be enabled in production")

        if self._contains_placeholder(self.api_keys):
            errors.append("AGENT_HUB_API_KEYS must not use placeholder values in production")

        if self._contains_placeholder(self.jwt_secret):
            errors.append("AGENT_HUB_JWT_SECRET must not use placeholder values in production")

        if self._contains_placeholder(self.github_webhook_secret):
            errors.append("AGENT_HUB_GITHUB_WEBHOOK_SECRET must not use placeholder values in production")

        if self._contains_placeholder(self.metrics_bearer_token):
            errors.append("AGENT_HUB_METRICS_BEARER_TOKEN must not use placeholder values in production")

        if self._contains_placeholder(self.database_url):
            errors.append("AGENT_HUB_DATABASE_URL must not use placeholder values in production")

        if self.rate_limit_trust_proxy_headers and not self.parsed_trusted_proxy_ips():
            errors.append("AGENT_HUB_TRUSTED_PROXY_IPS must be configured when trusting proxy headers")

        return errors



def get_settings() -> Settings:
    return Settings()
