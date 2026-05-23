"""Claude hook merging for `.claude/settings.json`."""

from __future__ import annotations

from ken.hooks_template import KEN_HOOKS, merge_settings, remove_ken_hooks


def test_merge_into_empty_yields_full_hook_set():
    merged, touched = merge_settings(None)

    assert set(merged["hooks"]) == set(KEN_HOOKS)
    assert set(touched) == set(KEN_HOOKS)


def test_merge_is_idempotent():
    once, _ = merge_settings(None)
    twice, touched = merge_settings(once)

    assert twice == once
    assert touched == []


def test_merge_preserves_user_entries():
    user = {
        "permissions": {"allow": ["Bash(pytest *)"]},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "echo user-pre"}],
                }
            ]
        },
    }

    merged, _ = merge_settings(user)

    assert merged["permissions"] == user["permissions"]
    pre = merged["hooks"]["PreToolUse"]
    cmds = {h["command"] for entry in pre for h in entry["hooks"]}
    assert "echo user-pre" in cmds
    assert "ken hook tool-call --phase pre" in cmds


def test_remove_strips_only_ken():
    user_then_ken, _ = merge_settings(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo user-pre"}],
                    }
                ]
            }
        }
    )

    cleaned = remove_ken_hooks(user_then_ken)

    pre = cleaned["hooks"]["PreToolUse"]
    cmds = {h["command"] for entry in pre for h in entry["hooks"]}
    assert "echo user-pre" in cmds
    assert "ken hook tool-call --phase pre" not in cmds


def test_remove_drops_event_when_empty():
    just_ken, _ = merge_settings(None)
    cleaned = remove_ken_hooks(just_ken)

    assert "hooks" not in cleaned or cleaned["hooks"] == {}


def test_session_start_uses_claude_sources_matcher():
    matcher = KEN_HOOKS["SessionStart"][0]["matcher"]

    assert "startup" in matcher
    assert "resume" in matcher
    assert "clear" in matcher
    assert "compact" in matcher
