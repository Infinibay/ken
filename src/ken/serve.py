"""`ken serve` — daemon that owns the file watcher, index queue, and the
HTTP API the hooks talk to.

Stub for v1 of the rewrite. The real implementation lands in the next
phase. For now we just confirm the project is installed and exit
non-zero with an actionable message — so users running `ken serve`
during the install bring-up get told what to expect.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ken import _paths


def serve(start: Path) -> int:
    root = _paths.find_project_root(start.resolve())
    if root is None:
        print(f"no ken project found at or above {start.resolve()}", file=sys.stderr)
        return 1
    print(f"`ken serve` is not yet implemented (project_root={root}).", file=sys.stderr)
    print("Phase 2 will start the daemon (file watcher + HTTP API).", file=sys.stderr)
    return 2
