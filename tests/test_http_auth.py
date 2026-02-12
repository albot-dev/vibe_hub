from __future__ import annotations

from app.http_auth import extract_bearer_token


def test_extract_bearer_token_accepts_valid_bearer_header() -> None:
    assert extract_bearer_token("Bearer abc123") == "abc123"
    assert extract_bearer_token("bearer abc123") == "abc123"
    assert extract_bearer_token("  Bearer   xyz   ") == "xyz"


def test_extract_bearer_token_rejects_invalid_values() -> None:
    assert extract_bearer_token(None) is None
    assert extract_bearer_token("") is None
    assert extract_bearer_token("Token abc123") is None
    assert extract_bearer_token("Bearer") is None
    assert extract_bearer_token("Bearer ") is None

