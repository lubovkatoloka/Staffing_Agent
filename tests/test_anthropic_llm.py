"""JSON parsing helpers for model output."""

from staffing_agent.anthropic_llm import _parse_json_object


def test_parse_json_object_strips_markdown_fence() -> None:
    raw = """```json
{"a": 1, "b": "ok"}
```"""
    assert _parse_json_object(raw) == {"a": 1, "b": "ok"}


def test_parse_json_object_finds_object_with_prose() -> None:
    raw = """Thought: here we go.
{"thread_kind": "deal_notification", "tier": null, "complexity_class": null, "tier_rationale": "", "project_type_tags": [], "summary": "x", "project_start_hint": null, "confidence": 0.2, "notes": ""}
"""
    d = _parse_json_object(raw)
    assert d["thread_kind"] == "deal_notification"
    assert d["summary"] == "x"
