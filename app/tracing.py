from __future__ import annotations

import secrets
import string
from dataclasses import dataclass


_HEX_CHARS = set(string.hexdigits)
_TRACEPARENT_VERSION = "00"


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: str

    @property
    def traceparent(self) -> str:
        return f"{_TRACEPARENT_VERSION}-{self.trace_id}-{self.span_id}-{self.trace_flags}"


def resolve_trace_context(traceparent_header: str | None) -> TraceContext:
    parsed = _parse_traceparent(traceparent_header)
    if parsed is None:
        return TraceContext(
            trace_id=_generate_hex(length=32),
            span_id=_generate_hex(length=16),
            trace_flags="01",
        )

    trace_id, trace_flags = parsed
    return TraceContext(
        trace_id=trace_id,
        span_id=_generate_hex(length=16),
        trace_flags=trace_flags,
    )


def _parse_traceparent(value: str | None) -> tuple[str, str] | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None

    parts = raw.split("-")
    if len(parts) != 4:
        return None

    version, trace_id, parent_id, trace_flags = parts
    if version != _TRACEPARENT_VERSION:
        return None
    if not _is_hex(trace_id, length=32) or set(trace_id) == {"0"}:
        return None
    if not _is_hex(parent_id, length=16) or set(parent_id) == {"0"}:
        return None
    if not _is_hex(trace_flags, length=2):
        return None
    return trace_id, trace_flags


def _is_hex(value: str, *, length: int) -> bool:
    return len(value) == length and all(char in _HEX_CHARS for char in value)


def _generate_hex(*, length: int) -> str:
    return secrets.token_hex(length // 2)
