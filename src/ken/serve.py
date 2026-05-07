"""`ken serve` entrypoint."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from ken import _paths
from ken.daemon.server import run as run_server


def serve(start: Path, *, background: bool = False) -> int:
    root = _paths.find_project_root(start.resolve()) or start.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"no ken project at {root} — run `ken install .` first", file=sys.stderr)
        return 1

    if background:
        # When spawned by a hook we want a friendly file log; otherwise
        # foreground mode logs to stderr so `ken serve` in a terminal is
        # interactive-debuggable.
        logging.basicConfig(
            filename=str(_paths.log_path(root)),
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    return run_server(root)
