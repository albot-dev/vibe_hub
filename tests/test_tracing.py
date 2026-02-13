from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as app_main


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("AGENT_HUB_REQUIRE_API_KEY", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_ROLES", "0")
    monkeypatch.setenv("AGENT_HUB_AUTH_REQUIRE_READS", "0")
    monkeypatch.setenv("AGENT_HUB_JOB_WORKER_ENABLED", "0")
    monkeypatch.setenv("AGENT_HUB_DATABASE_URL", f"sqlite:///{tmp_path / 'test_tracing.db'}")
    app_main._rate_limiter = None
    app_main._rate_limiter_rpm = None
    with TestClient(app_main.app) as test_client:
        yield test_client


def test_health_response_includes_generated_trace_headers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    trace_id = response.headers.get("X-Trace-ID")
    traceparent = response.headers.get("traceparent")
    assert trace_id is not None
    assert traceparent is not None
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", traceparent)
    assert traceparent.split("-")[1] == trace_id


def test_health_response_reuses_incoming_trace_id(client: TestClient) -> None:
    incoming = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    response = client.get("/health", headers={"traceparent": incoming})
    assert response.status_code == 200

    returned_trace_id = response.headers["X-Trace-ID"]
    returned_traceparent = response.headers["traceparent"]
    parts = returned_traceparent.split("-")

    assert returned_trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert parts[0] == "00"
    assert parts[1] == returned_trace_id
    assert parts[2] != "00f067aa0ba902b7"
    assert re.fullmatch(r"[0-9a-f]{16}", parts[2])
    assert parts[3] == "01"


def test_invalid_traceparent_header_falls_back_to_new_trace(client: TestClient) -> None:
    response = client.get("/health", headers={"traceparent": "invalid-header"})
    assert response.status_code == 200

    trace_id = response.headers["X-Trace-ID"]
    traceparent = response.headers["traceparent"]
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}", traceparent)
