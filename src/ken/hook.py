"""Short-lived hook shims invoked by supported coding agents.

Each `ken hook ...` subcommand reads the agent's JSON event payload from
stdin, finds the installed project via walk-up, and POSTs an event to
the per-project daemon, spawning it if needed.

Hooks **never** raise to the caller:
  * If we can't find a project, we print to stderr and exit 0 — the
    user just isn't in a ken-installed project.
  * If the daemon can't be reached after a spawn attempt, we log
    silently and exit 0 — keeping ken from blocking the agent is more
    important than capturing every event.

Stdout is reserved for hook-driven context injection. On
`UserPromptSubmit`, the daemon may return a `<context-rank>` block and
the hook prints only that block so the host CLI can prepend it to the
model-visible prompt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
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
            # the host CLI prepends it to the model's view of the prompt.
            block = (resp or {}).get("context_block") or ""
            if block.strip():
                sys.stdout.write(block)
        elif args.hook_cmd == "tool-call":
            phase_path = "/tools/pre" if args.phase == "pre" else "/tools/post"
            client.post(root, phase_path, _tool_call_body(session_id, args.phase, payload))
        elif args.hook_cmd == "stop":
            # Codex passes ``last_assistant_message`` directly in the
            # payload; Claude Code passes a ``transcript_path`` we tail-
            # read. Prefer the direct field when present.
            direct = payload.get("last_assistant_message")
            if isinstance(direct, str) and direct:
                assistant_text = direct
            else:
                assistant_text = _extract_last_assistant_text(payload.get("transcript_path"))
            client.post(
                root,
                "/turn-end",
                {"session_id": session_id, "assistant_text": assistant_text},
            )
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
    """Project a hook tool payload into the daemon's tool-call API.

    Claude Code and Codex use slightly different field names, so this
    helper accepts both the explicit hook shape (`tool_name`,
    `tool_input`, `tool_response`) and ken's already-normalized shape
    (`tool`, `input`, `output`).
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


def _extract_last_assistant_text(
    transcript_path: Any, max_bytes: int = 50_000
) -> str:
    """Return concatenated text content of the most recent assistant entry.

    Some hosts provide the final assistant text directly; Claude Code
    instead gives us a transcript JSONL path on `Stop`. We tail the last
    ~50 KB, walk backwards to the latest ``type=assistant`` line, and
    pull out text content blocks. Returns ``""`` on any error because
    missing transcript signal should not block the hook.
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return ""
    p = Path(transcript_path)
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # discard the partial first line
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""

    for raw in reversed(chunk.splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message") or {}
        content = msg.get("content") or []
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    txt = block.get("text")
                    if isinstance(txt, str):
                        texts.append(txt)
            return "\n".join(texts)
        return ""
    return ""


__all__ = ["dispatch_hook"]
