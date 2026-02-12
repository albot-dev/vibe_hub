from __future__ import annotations

import pytest

from app.providers import RuleBasedProvider, get_provider


def test_default_provider_is_rule_based(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_HUB_PROVIDER", raising=False)
    provider = get_provider()
    assert isinstance(provider, RuleBasedProvider)


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        get_provider("unknown-provider")


def test_openai_provider_falls_back_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_HUB_PROVIDER_FALLBACK", raising=False)

    with pytest.warns(RuntimeWarning):
        provider = get_provider()
    assert isinstance(provider, RuleBasedProvider)


def test_openai_provider_strict_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_HUB_PROVIDER_FALLBACK", "0")

    with pytest.raises(ValueError):
        get_provider()
