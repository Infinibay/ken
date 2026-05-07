"""`ken hook ...` — short-lived shims invoked by Claude Code hooks.

For Phase 1 these are *stubs*: they find the project, optionally read
the JSON payload Claude Code passes on stdin, and append a minimal
note to a debug log inside `.ken/`. No DB writes yet.

The point of having them now is to verify the install pipeline:

    ken install .
    cd <project>
    claude          # → SessionStart fires → `ken hook session-start` → log line

Phase 2 swaps these stubs for HTTP calls into the daemon, which does
the actual DB writes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ken import _paths
from ken.cli import _read_hook_payload


HOOK_LOG = "hook-debug.log"


def dispatch_hook(args: argparse.Namespace) -> int:
    root = _paths.find_project_root()
    if root is None:
        # Hooks should never block claude — log to stderr and exit 0.
        print("ken: no .ken project at or above cwd, skipping hook", file=sys.stderr)
        return 0

    payload = _read_hook_payload()
    event = _event_label(args)

    log_p = _paths.ken_dir(root) / HOOK_LOG
    line = json.dumps(
        {
            "ts": int(time.time() * 1000),
            "event": event,
            "payload_keys": sorted(payload.keys()),
            "cwd": str(Path.cwd()),
        }
    )
    try:
        with log_p.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:  # pragma: no cover
        print(f"ken: failed to write hook log: {exc}", file=sys.stderr)

    # Phase 2 will:
    #   - session-start: register session in cr_sessions, ensure daemon up.
    #   - session-end:   set ended_at, decrement active-session count, schedule daemon shutdown.
    #   - user-prompt:   write cr_contexts row, query ranker, print <context-rank> block on stdout.
    #   - tool-call:     write cr_interactions row.
    #   - stop:          flush + snapshot scores.
    return 0


def _event_label(args: argparse.Namespace) -> str:
    if args.hook_cmd == "tool-call":
        return f"tool-call:{args.phase}"
    return args.hook_cmd
