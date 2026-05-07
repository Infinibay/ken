"""`ken install` — wire a project up for ken.

Steps:
  1. Validate / create `.ken/` inside the project root.
  2. Generate a project_id (uuid) + auth token, persist to `.ken/meta.json`.
  3. Open / create the SQLite DB, apply the schema.
  4. Add `.ken/` to the project's `.gitignore` (if there is one and the
     entry isn't there yet).
  5. Merge ken's hook entries into `.claude/settings.json`.
  6. Run the initial code index, verbose by default.

Idempotent. Re-running on an installed project re-applies the schema
(noop), re-merges hooks (dedup), and runs an incremental re-index
(unchanged files short-circuit on hash).
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from ken import _paths
from ken.db import connect, init_schema, set_meta
from ken.gitignore_filter import iter_files
from ken.hooks_template import merge_settings, write_settings
from ken.indexer import index_files

CLAUDE_SETTINGS = ".claude/settings.json"


@dataclass
class InstallResult:
    project_root: Path
    project_id: str
    db_path: Path
    files_indexed: int
    symbols: int
    elapsed_s: float


def install(project_path: Path, *, verbose: bool = True) -> InstallResult:
    """Install ken into *project_path*.  Prints progress to stdout."""
    root = project_path.resolve()
    if not root.is_dir():
        raise SystemExit(f"error: not a directory: {root}")

    ken_dir = _paths.ken_dir(root)
    ken_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: meta.json — generate a project id + auth token if missing.
    meta_p = _paths.meta_path(root)
    if meta_p.is_file():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if verbose:
            print(f"[meta] reusing existing project_id={meta['project_id']}")
    else:
        meta = {
            "project_id": str(uuid.uuid4()),
            "auth_token": secrets.token_urlsafe(32),
            "created_at_ms": int(time.time() * 1000),
            "project_path": str(root),
        }
        meta_p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if verbose:
            print(f"[meta] created .ken/meta.json (project_id={meta['project_id']})")

    # Step 2: DB schema.
    db_p = _paths.db_path(root)
    fresh_db = not db_p.is_file()
    conn = connect(db_p)
    try:
        init_schema(conn)
        set_meta(conn, "project_id", meta["project_id"])
        set_meta(conn, "ken_version", _ken_version())
        if verbose:
            print(f"[db] {'created' if fresh_db else 'opened'} {db_p.relative_to(root)}")

        # Step 3: .gitignore — add `.ken/` if there's a gitignore at project root.
        _ensure_gitignore(root, verbose=verbose)

        # Step 4: Claude Code hooks.
        _wire_claude_hooks(root, verbose=verbose)

        # Step 5: initial index.
        if verbose:
            print("[index] walking project (respecting .gitignore)…")
        rels = list(iter_files(root))
        if verbose:
            print(f"[index] {len(rels)} candidate files; parsing…")

        def progress(rel: str, status: str) -> None:
            if not verbose:
                return
            # Compact one-line-per-file format. `indexed:noparse` files are
            # the silent majority on a real project (assets, configs, docs)
            # so we suppress them unless --very-verbose later.
            if status == "indexed":
                print(f"  + {rel}")
            elif status.startswith("skipped:"):
                print(f"  ! {rel}  ({status[len('skipped:'):]})")

        stats = index_files(conn, root, rels, on_progress=progress)
        if verbose:
            print()
            print(
                f"[index] done in {stats.elapsed_s:.1f}s — "
                f"parsed={stats.parsed}, unchanged={stats.unchanged}, "
                f"no-parser={stats.skipped_no_lang}, too-large={stats.skipped_too_large}, "
                f"io-errors={stats.skipped_io_error}, "
                f"symbols={stats.symbols}, imports={stats.imports}"
            )
    finally:
        conn.close()

    if verbose:
        print()
        print(f"✓ ken installed in {root}")
        print(f"  next: cd {root} && claude")

    return InstallResult(
        project_root=root,
        project_id=meta["project_id"],
        db_path=db_p,
        files_indexed=stats.parsed,
        symbols=stats.symbols,
        elapsed_s=stats.elapsed_s,
    )


def _ensure_gitignore(root: Path, *, verbose: bool) -> None:
    gi = root / ".gitignore"
    line = ".ken/"
    if not gi.is_file():
        if verbose:
            print(f"[gitignore] no .gitignore at project root — skipping (you may want to add `{line}`)")
        return
    existing = gi.read_text(encoding="utf-8", errors="replace").splitlines()
    if any(s.strip() == line.rstrip("/") or s.strip() == line for s in existing):
        if verbose:
            print(f"[gitignore] `{line}` already present — leaving alone")
        return
    sep = "" if (existing and existing[-1].strip() == "") else "\n"
    appended = f"{sep}\n# ken — local index, daemon socket, logs\n{line}\n"
    with gi.open("a", encoding="utf-8") as fh:
        fh.write(appended)
    if verbose:
        print(f"[gitignore] appended `{line}` to .gitignore")


def _wire_claude_hooks(root: Path, *, verbose: bool) -> None:
    settings_p = root / CLAUDE_SETTINGS
    existing: dict | None = None
    if settings_p.is_file():
        try:
            existing = json.loads(settings_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[hooks] {settings_p} is not valid JSON ({exc}); aborting", file=sys.stderr)
            raise SystemExit(2)
    merged, touched = merge_settings(existing)
    write_settings(settings_p, merged)
    if verbose:
        if touched:
            print(f"[hooks] wired {', '.join(touched)} into {CLAUDE_SETTINGS}")
        else:
            print(f"[hooks] {CLAUDE_SETTINGS} already had ken hooks — left alone")


def _ken_version() -> str:
    from ken import __version__

    return __version__
