"""`ken status` — quick health check on the current project."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ken import _paths
from ken.db import connect


def show_status(start: Path) -> int:
    root = _paths.find_project_root(start.resolve())
    if root is None:
        print(f"no ken project found at or above {start.resolve()}", file=sys.stderr)
        print("hint: `ken install .` from a project root", file=sys.stderr)
        return 1

    meta = json.loads(_paths.meta_path(root).read_text(encoding="utf-8"))
    db_p = _paths.db_path(root)

    print(f"project_root  : {root}")
    print(f"project_id    : {meta['project_id']}")
    print(f"db            : {db_p}  ({_human_size(db_p)})")

    if not db_p.is_file():
        print("(no DB yet — run `ken install .`)")
        return 0

    conn = connect(db_p)
    try:
        files = conn.execute("SELECT COUNT(*) AS n FROM ci_files").fetchone()["n"]
        symbols = conn.execute("SELECT COUNT(*) AS n FROM ci_symbols").fetchone()["n"]
        sessions = conn.execute("SELECT COUNT(*) AS n FROM cr_sessions").fetchone()["n"]
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM cr_sessions WHERE ended_at IS NULL"
        ).fetchone()["n"]
        contexts = conn.execute("SELECT COUNT(*) AS n FROM cr_contexts").fetchone()["n"]
        interactions = conn.execute("SELECT COUNT(*) AS n FROM cr_interactions").fetchone()["n"]
    finally:
        conn.close()

    print(f"files indexed : {files}")
    print(f"symbols       : {symbols}")
    print(f"sessions      : {sessions} total, {active} active")
    print(f"contexts      : {contexts}")
    print(f"interactions  : {interactions}")
    return 0


def _human_size(p: Path) -> str:
    if not p.is_file():
        return "missing"
    size = p.stat().st_size
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TiB"
