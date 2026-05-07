"""Project-root discovery + canonical paths inside `.ken/`.

A "ken project" is any directory that contains a `.ken/meta.json`. We
follow git's pattern: walk up from the caller's cwd until we find one,
otherwise return None.

The hook commands (`ken hook session-start`, etc.) call
`find_project_root()` first thing so they know which DB to write to.
The CLI's `install` / `serve` / `status` accept an explicit path
argument that takes precedence.
"""

from __future__ import annotations

import os
from pathlib import Path

KEN_DIR_NAME = ".ken"
META_FILENAME = "meta.json"
DB_FILENAME = "ken.db"
PID_FILENAME = "daemon.pid"
SOCKET_FILENAME = "daemon.sock"
PORT_FILENAME = "daemon.port"
LOG_FILENAME = "daemon.log"


def ken_dir(project_root: Path) -> Path:
    return project_root / KEN_DIR_NAME


def meta_path(project_root: Path) -> Path:
    return ken_dir(project_root) / META_FILENAME


def db_path(project_root: Path) -> Path:
    return ken_dir(project_root) / DB_FILENAME


def pid_path(project_root: Path) -> Path:
    return ken_dir(project_root) / PID_FILENAME


def port_path(project_root: Path) -> Path:
    return ken_dir(project_root) / PORT_FILENAME


def log_path(project_root: Path) -> Path:
    return ken_dir(project_root) / LOG_FILENAME


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default cwd) looking for `.ken/meta.json`.

    Returns the directory that contains `.ken/`, not the `.ken/` itself.
    `KEN_PROJECT_ROOT` env var overrides discovery — useful for tests
    and for hooks invoked with a wonky cwd.
    """
    forced = os.environ.get("KEN_PROJECT_ROOT")
    if forced:
        p = Path(forced).expanduser().resolve()
        return p if meta_path(p).is_file() else None

    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        if meta_path(parent).is_file():
            return parent
    return None
