"""Codex hook merging + MCP block manipulation."""

from __future__ import annotations

from ken.codex_hooks_template import (
    KEN_CODEX_HOOKS,
    KEN_MCP_BLOCK,
    append_ken_mcp_block,
    has_ken_mcp_block,
    merge_codex_hooks,
    remove_ken_codex_hooks,
    remove_ken_mcp_block,
)


def test_merge_into_empty_yields_full_hook_set():
    merged, touched = merge_codex_hooks(None)
    assert set(merged["hooks"]) == set(KEN_CODEX_HOOKS)
    assert set(touched) == set(KEN_CODEX_HOOKS)


def test_merge_is_idempotent():
    """Re-running merge on its own output adds nothing new."""
    once, _ = merge_codex_hooks(None)
    twice, touched = merge_codex_hooks(once)
    assert touched == []
    assert twice == once


def test_merge_preserves_user_entries():
    user = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": "echo user-pre"}],
                }
            ]
        },
        "model": "gpt-5",  # arbitrary user key
    }
    merged, _ = merge_codex_hooks(user)
    assert merged["model"] == "gpt-5"
    pre = merged["hooks"]["PreToolUse"]
    cmds = {h["command"] for entry in pre for h in entry["hooks"]}
    assert "echo user-pre" in cmds  # user kept
    assert "ken hook tool-call --phase pre" in cmds  # ken added


def test_remove_strips_only_ken():
    user_then_ken, _ = merge_codex_hooks(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Read",
                        "hooks": [{"type": "command", "command": "echo user-pre"}],
                    }
                ]
            }
        }
    )
    cleaned = remove_ken_codex_hooks(user_then_ken)
    pre = cleaned["hooks"]["PreToolUse"]
    cmds = {h["command"] for entry in pre for h in entry["hooks"]}
    assert "echo user-pre" in cmds
    assert "ken hook tool-call --phase pre" not in cmds


def test_remove_drops_event_when_empty():
    """If ken was the only thing in an event, the event key disappears."""
    just_ken, _ = merge_codex_hooks(None)
    cleaned = remove_ken_codex_hooks(just_ken)
    # No ken-only event survives.
    assert "hooks" not in cleaned or cleaned["hooks"] == {}


def test_session_start_uses_codex_matcher():
    """Codex SessionStart matcher must include 'startup|resume' so we get
    both fresh starts and `codex resume` invocations."""
    matcher = KEN_CODEX_HOOKS["SessionStart"][0]["matcher"]
    assert "startup" in matcher
    assert "resume" in matcher


def test_no_session_end_event():
    """Codex doesn't emit SessionEnd — we rely on idle-timeout."""
    assert "SessionEnd" not in KEN_CODEX_HOOKS


# ── MCP TOML helpers ────────────────────────────────────────────────


def test_append_to_empty_file():
    out = append_ken_mcp_block("")
    assert out == KEN_MCP_BLOCK
    assert has_ken_mcp_block(out)


def test_append_preserves_existing_content():
    cur = '[some_other]\nkey = "v"\n'
    out = append_ken_mcp_block(cur)
    assert "[some_other]" in out
    assert KEN_MCP_BLOCK in out


def test_has_ken_block_detects_section_header():
    assert has_ken_mcp_block(KEN_MCP_BLOCK) is True
    assert has_ken_mcp_block("[mcp_servers.other]\ncommand = 'x'\n") is False
    assert has_ken_mcp_block("") is False


def test_remove_strips_block():
    cur = f'[other]\nx = 1\n\n{KEN_MCP_BLOCK}'
    cleaned = remove_ken_mcp_block(cur)
    assert "[other]" in cleaned
    assert "[mcp_servers.ken]" not in cleaned


def test_remove_user_edited_block_falls_back_to_line_strip():
    """If the user added an extra arg, the exact-match path won't hit;
    we still strip the section header + 2 following lines."""
    cur = (
        '[other]\nx = 1\n'
        '[mcp_servers.ken]\n'
        'command = "ken"\n'
        'args = ["mcp", "--debug"]\n'
        '[after]\ny = 2\n'
    )
    cleaned = remove_ken_mcp_block(cur)
    assert "[other]" in cleaned
    assert "[after]" in cleaned
    assert "[mcp_servers.ken]" not in cleaned
