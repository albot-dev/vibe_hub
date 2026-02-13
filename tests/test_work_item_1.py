from __future__ import annotations

from agent_codegen.work_item_1 import describe_work_item


def test_describe_work_item_contains_metadata() -> None:
    payload = describe_work_item()
    assert payload["work_item_id"] == "1"
    assert payload["project"] == "dogfood-albot-dev-vibe_hub"
    assert payload["title"]
