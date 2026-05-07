"""Hook helpers — payload projection + transcript tail-reading."""

from __future__ import annotations

import json
from pathlib import Path

from ken.hook import _extract_last_assistant_text, _session_id, _tool_call_body


# ── _session_id ────────────────────────────────────────────────────


def test_session_id_extracts_string():
    assert _session_id({"session_id": "abc-123"}) == "abc-123"


def test_session_id_returns_none_for_missing_or_wrong_type():
    assert _session_id({}) is None
    assert _session_id({"session_id": ""}) is None
    assert _session_id({"session_id": 42}) is None


# ── _tool_call_body ────────────────────────────────────────────────


def test_tool_call_body_pre_phase():
    body = _tool_call_body(
        "sess-1",
        "pre",
        {"tool_name": "Read", "tool_input": {"file_path": "src/a.py"}},
    )
    assert body == {
        "session_id": "sess-1",
        "tool": "Read",
        "input": {"file_path": "src/a.py"},
    }


def test_tool_call_body_post_carries_output_and_success():
    body = _tool_call_body(
        "sess-1",
        "post",
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/a.py"},
            "tool_response": {"ok": True},
            "success": False,
        },
    )
    assert body["session_id"] == "sess-1"
    assert body["tool"] == "Edit"
    assert body["output"] == {"ok": True}
    assert body["success"] is False


def test_tool_call_body_post_defaults_success_to_true():
    body = _tool_call_body("sess-1", "post", {"tool_name": "Read", "tool_input": {}})
    assert body["success"] is True


# ── _extract_last_assistant_text ───────────────────────────────────


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_extract_returns_text_blocks_concatenated(tmp_path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"type": "user", "message": {"content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "tool_use", "id": "x"},
                    {"type": "text", "text": "second"},
                ]
            },
        },
    ])
    out = _extract_last_assistant_text(str(p))
    assert out == "first\nsecond"


def test_extract_handles_no_assistant_returns_empty(tmp_path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [{"type": "user", "message": {"content": "hi"}}])
    assert _extract_last_assistant_text(str(p)) == ""


def test_extract_picks_most_recent_assistant(tmp_path):
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
        {"type": "user", "message": {"content": "ok"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "latest"}]}},
    ])
    assert _extract_last_assistant_text(str(p)) == "latest"


def test_extract_tails_large_file(tmp_path):
    """When the file > max_bytes, we read only the tail. The latest
    assistant must still come back if it's near the end."""
    p = tmp_path / "transcript.jsonl"
    filler = [{"type": "user", "message": {"content": "x" * 200}} for _ in range(500)]
    last = {"type": "assistant", "message": {"content": [{"type": "text", "text": "found"}]}}
    _write_jsonl(p, filler + [last])
    # File is well over 50KB now.
    assert p.stat().st_size > 60_000
    assert _extract_last_assistant_text(str(p)) == "found"


def test_extract_ignores_malformed_lines(tmp_path):
    p = tmp_path / "transcript.jsonl"
    p.write_text(
        "not json\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}})
        + "\nmore garbage\n",
        encoding="utf-8",
    )
    assert _extract_last_assistant_text(str(p)) == "ok"


def test_extract_handles_string_content(tmp_path):
    """Older transcripts use a plain string instead of a content list."""
    p = tmp_path / "transcript.jsonl"
    _write_jsonl(p, [{"type": "assistant", "message": {"content": "plain"}}])
    assert _extract_last_assistant_text(str(p)) == "plain"


def test_extract_handles_missing_file():
    assert _extract_last_assistant_text("/no/such/path.jsonl") == ""
    assert _extract_last_assistant_text(None) == ""
    assert _extract_last_assistant_text("") == ""
