from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security import _matches_any_api_key, require_write_access


def test_matches_any_api_key_returns_true_for_exact_match() -> None:
    assert _matches_any_api_key("abc123", {"abc123", "other"}) is True


def test_matches_any_api_key_returns_false_for_missing_or_empty() -> None:
    assert _matches_any_api_key("", {"abc123"}) is False
    assert _matches_any_api_key("missing", {"abc123"}) is False


def test_require_write_access_noop_when_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    require_write_access(x_api_key=None, authorization=None)


def test_require_write_access_accepts_header_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "abc123,other")
    require_write_access(x_api_key="abc123", authorization=None)


def test_require_write_access_accepts_bearer_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "abc123,other")
    require_write_access(x_api_key=None, authorization="Bearer other")


def test_require_write_access_rejects_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "abc123")
    with pytest.raises(HTTPException, match="Invalid or missing API key"):
        require_write_access(x_api_key="nope", authorization=None)


def test_require_write_access_rejects_when_no_keys_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "1")
    monkeypatch.setenv("AGENT_HUB_API_KEYS", "")
    with pytest.raises(HTTPException, match="no keys configured"):
        require_write_access(x_api_key="abc123", authorization=None)

