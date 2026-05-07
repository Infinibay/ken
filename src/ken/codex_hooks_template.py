"""Generate / merge `.codex/hooks.json` for Codex CLI integration.

Codex CLI's lifecycle hook system is structurally similar to Claude
Code's: a ``hooks`` table mapping event names to a list of matcher
groups, each containing a ``hooks`` list of command handlers.

Differences vs Claude Code:

* Hooks live at ``<project>/.codex/hooks.json`` (not ``.claude/settings.json``).
* No ``SessionEnd`` event — Codex emits ``Stop`` at end of each turn.
  We rely on the daemon's idle-shutdown for cleanup instead.
* ``Stop`` payload carries ``last_assistant_message`` directly; the
  hook script handles both that and Claude Code's ``transcript_path``.
* Project-local hooks load only when the user marked the project
  ``trust_level = "trusted"`` in ``~/.codex/config.toml``. ``ken install``
  prints an instruction; we don't auto-edit user-level config.

Same idempotent merge contract as ``hooks_template.merge_settings``:
re-running ``ken install`` deduplicates by command string.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

KEN_CODEX_HOOKS: dict[str, list[dict[str, Any]]] = {
    "SessionStart": [
        {
            "matcher": "startup|resume",
            "hooks": [{"type": "command", "command": "ken hook session-start"}],
        }
    ],
    "UserPromptSubmit": [
        {
            "hooks": [{"type": "command", "command": "ken hook user-prompt"}],
        }
    ],
    "PreToolUse": [
        {
            "matcher": "Bash|apply_patch",
            "hooks": [{"type": "command", "command": "ken hook tool-call --phase pre"}],
        }
    ],
    "PostToolUse": [
        {
            "matcher": "Bash|apply_patch",
            "hooks": [{"type": "command", "command": "ken hook tool-call --phase post"}],
        }
    ],
    "Stop": [
        {
            "hooks": [{"type": "command", "command": "ken hook stop"}],
        }
    ],
}


def merge_codex_hooks(existing: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Return ``(merged_hooks_doc, events_touched)``.

    The ``hooks.json`` document has top-level shape ``{"hooks": {...}}``.
    Existing entries with the same command string are not duplicated.
    """
    merged = deepcopy(existing) if existing else {}
    hooks_section = merged.setdefault("hooks", {})
    touched: list[str] = []
    for event, ken_entries in KEN_CODEX_HOOKS.items():
        cur = hooks_section.setdefault(event, [])
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


def remove_ken_codex_hooks(existing: dict[str, Any]) -> dict[str, Any]:
    """Inverse of merge: drop entries whose commands start with ``ken hook``."""
    out = deepcopy(existing)
    hooks_section = out.get("hooks") or {}
    for event in list(hooks_section.keys()):
        kept: list[dict[str, Any]] = []
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


def write_codex_hooks(path: Path, merged: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")


def _commands_in(entries: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for e in entries:
        for h in e.get("hooks", []) or []:
            cmd = h.get("command")
            if isinstance(cmd, str):
                out.add(cmd)
    return out


# ── MCP server registration in .codex/config.toml ──────────────────

KEN_MCP_BLOCK = '''\
[mcp_servers.ken]
command = "ken"
args = ["mcp"]
'''


def has_ken_mcp_block(toml_text: str) -> bool:
    """Cheap check: does the TOML already register the ``ken`` MCP server?

    We don't need a full TOML parser — the section header is a stable
    string. False negatives would cause an idempotent re-install to
    duplicate the block, which is why we still match liberally.
    """
    return "[mcp_servers.ken]" in toml_text


def append_ken_mcp_block(toml_text: str) -> str:
    """Append the ``[mcp_servers.ken]`` section, preserving prior content."""
    if not toml_text:
        return KEN_MCP_BLOCK
    sep = "" if toml_text.endswith("\n\n") else ("\n" if toml_text.endswith("\n") else "\n\n")
    return f"{toml_text}{sep}{KEN_MCP_BLOCK}"


def remove_ken_mcp_block(toml_text: str) -> str:
    """Strip the ken MCP section we previously appended.

    We only remove a contiguous block matching our exact template — we
    leave other sections (and any user-extended ken entries) alone.
    """
    if KEN_MCP_BLOCK in toml_text:
        return toml_text.replace(KEN_MCP_BLOCK, "")
    # User edited the block: try to remove just the section header line
    # plus the next two lines (command/args).
    lines = toml_text.splitlines(keepends=True)
    out: list[str] = []
    skip = 0
    for line in lines:
        if skip > 0:
            skip -= 1
            continue
        if line.strip() == "[mcp_servers.ken]":
            skip = 2  # drop next two lines (command, args)
            continue
        out.append(line)
    return "".join(out)
