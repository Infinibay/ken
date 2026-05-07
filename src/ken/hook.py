"""`ken hook ...` — short-lived shims invoked by Claude Code hooks.

Each subcommand reads Claude Code's JSON event payload from stdin,
finds the project via walk-up, and POSTs an event to the per-project
daemon (spawning it if it isn't running yet).

Hooks **never** raise to Claude Code:
  * If we can't find a project, we print to stderr and exit 0 — the
    user just isn't in a ken-installed project.
  * If the daemon can't be reached after a spawn attempt, we log
    silently and exit 0 — keeping ken from blocking Claude is more
    important than capturing every event.

Stdout is reserved for hook-driven *injection* (`UserPromptSubmit`
prepends to Claude's context). Until Phase 5 wires the ranker, we
print nothing extra.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ken import _paths
from ken.cli import _read_hook_payload
from ken.daemon import client


def dispatch_hook(args: argparse.Namespace) -> int:
    root = _paths.find_project_root()
    if root is None:
        print("ken: no .ken project at or above cwd, skipping hook", file=sys.stderr)
        return 0

    payload = _read_hook_payload()
    session_id = _session_id(payload)
    if not session_id:
        print("ken: hook payload missing session_id; skipping", file=sys.stderr)
        return 0

    try:
        if args.hook_cmd == "session-start":
            client.post(root, "/sessions/start", {"session_id": session_id, "cwd": payload.get("cwd")})
        elif args.hook_cmd == "session-end":
            client.post(root, "/sessions/end", {"session_id": session_id})
        elif args.hook_cmd == "user-prompt":
            resp = client.post(
                root,
                "/prompts",
                {"session_id": session_id, "prompt": payload.get("prompt", "")},
            )
            # The daemon may want to inject context — print it to stdout so
            # Claude Code prepends it to the model's view of the prompt.
            block = (resp or {}).get("context_block") or ""
            if block.strip():
                sys.stdout.write(block)
        elif args.hook_cmd == "tool-call":
            phase_path = "/tools/pre" if args.phase == "pre" else "/tools/post"
            client.post(root, phase_path, _tool_call_body(session_id, args.phase, payload))
        elif args.hook_cmd == "stop":
            client.post(root, "/turn-end", {"session_id": session_id})
        else:
            print(f"ken: unknown hook subcommand: {args.hook_cmd}", file=sys.stderr)
            return 0
    except Exception as exc:  # pragma: no cover - belt + suspenders
        print(f"ken: hook error ({args.hook_cmd}): {exc}", file=sys.stderr)
    return 0


def _session_id(payload: dict[str, Any]) -> str | None:
    sid = payload.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    return None


def _tool_call_body(session_id: str, phase: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Project a Claude Code PreToolUse / PostToolUse payload into the
    daemon's tool-call API.

    Claude Code's payload uses ``tool_name`` + ``tool_input`` + (post)
    ``tool_response`` / ``success``.  We pass through whatever we got
    so the daemon can record it without us caring about minor schema
    drift.
    """
    body: dict[str, Any] = {
        "session_id": session_id,
        "tool": payload.get("tool_name") or payload.get("tool") or "",
        "input": payload.get("tool_input") or payload.get("input") or {},
    }
    if phase == "post":
        body["output"] = payload.get("tool_response") or payload.get("output")
        body["success"] = bool(payload.get("success", True))
    return body


__all__ = ["dispatch_hook"]
