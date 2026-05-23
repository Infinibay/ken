"""Generate / merge `.claude/settings.json` hook entries for ken.

Claude Code's hook config lives at `<project>/.claude/settings.json` (or
`settings.local.json`).  We don't want to clobber whatever the user
already has in there — so we *merge*: keep existing top-level keys
intact, append our hook entries to whatever's already registered for
the events we care about, deduplicating by command string.

The hook commands are deliberately bare (`ken hook session-start`,
etc.) — `ken` resolves the project via `find_project_root()`, so the
same settings file is portable across users / machines (no absolute
paths baked in).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

# Order matters here only for readability when the file is opened in an
# editor — Claude Code accepts hooks in any order.
KEN_HOOKS: dict[str, list[dict[str, Any]]] = {
    "SessionStart": [
        {
            "matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "command": "ken hook session-start"}],
        }
    ],
    "SessionEnd": [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "ken hook session-end"}],
        }
    ],
    "UserPromptSubmit": [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "ken hook user-prompt"}],
        }
    ],
    "PreToolUse": [
        {
            "matcher": "Read|Edit|Write|MultiEdit|Glob|Grep|Bash",
            "hooks": [{"type": "command", "command": "ken hook tool-call --phase pre"}],
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Read|Edit|Write|MultiEdit|Glob|Grep|Bash",
            "hooks": [{"type": "command", "command": "ken hook tool-call --phase post"}],
        }
    ],
    "Stop": [
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": "ken hook stop"}],
        }
    ],
}


def merge_settings(existing: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Return ``(merged_settings, events_touched)``.

    Events that already had a ken command registered are not duplicated.
    """
    merged = deepcopy(existing) if existing else {}
    hooks_section = merged.setdefault("hooks", {})
    touched: list[str] = []
    for event, ken_entries in KEN_HOOKS.items():
        cur = hooks_section.setdefault(event, [])
        # `cur` is a list of {matcher, hooks: [{type, command}, ...]}
        # entries.  We dedupe by command string — re-running `ken install`
        # must be idempotent.
        existing_cmds = _commands_in(cur)
        appended = False
        for entry in ken_entries:
            ken_cmds = _commands_in([entry])
            if any(cmd in existing_cmds for cmd in ken_cmds):
                continue
            cur.append(entry)
            appended = True
        if appended:
            touched.append(event)
    return merged, touched


def _commands_in(entries: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for e in entries:
        for h in e.get("hooks", []) or []:
            cmd = h.get("command")
            if isinstance(cmd, str):
                out.add(cmd)
    return out


def write_settings(path: Path, merged: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def remove_ken_hooks(existing: dict[str, Any]) -> dict[str, Any]:
    """Inverse of merge: drop only the entries whose commands start with
    ``ken hook`` from each event we touched. Used by `ken uninstall`.
    Anything else the user added is left alone.
    """
    out = deepcopy(existing)
    hooks_section = out.get("hooks") or {}
    for event in list(hooks_section.keys()):
        kept = []
        for entry in hooks_section[event]:
            inner = entry.get("hooks") or []
            inner_kept = [h for h in inner if not str(h.get("command", "")).startswith("ken hook")]
            if inner_kept:
                kept.append({**entry, "hooks": inner_kept})
        if kept:
            hooks_section[event] = kept
        else:
            del hooks_section[event]
    if not hooks_section:
        out.pop("hooks", None)
    return out
