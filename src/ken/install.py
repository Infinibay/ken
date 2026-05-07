"""`ken install` — wire a project up for ken.

Steps:
  1. Validate / create `.ken/` inside the project root.
  2. Generate a project_id (uuid) + auth token, persist to `.ken/meta.json`.
  3. Open / create the SQLite DB, apply the schema.
  4. Add `.ken/` to the project's `.gitignore` (if there is one and the
     entry isn't there yet).
  5. Merge ken's hook entries into `.claude/settings.json`.
  6. Register ken in `.mcp.json`.
  7. Merge Codex hooks and MCP config into `.codex/`.
  8. Run the initial code index, verbose by default. Embeddings are
     optional via ``ken install --embed`` because full-repo embedding can
     be expensive on very large codebases.

``ken install --claude`` is accepted as an explicit/symmetric spelling
for the default Claude Code wiring. ``ken install --codex`` additionally
forces repair of Codex project-local config when needed.

Idempotent. Re-running on an installed project re-applies the schema
(noop), re-merges hooks (dedup), and runs an incremental re-index
(unchanged files short-circuit on hash).
"""

from __future__ import annotations

import json
import secrets
import stat
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
MCP_SETTINGS = ".mcp.json"
CODEX_HOOKS_FILE = ".codex/hooks.json"
CODEX_CONFIG_FILE = ".codex/config.toml"
EMBED_PRIORITY_SUFFIXES = {
    ".py",
    ".rs",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".java",
    ".c",
    ".h",
}
LOW_PRIORITY_PARTS = {
    ".github",
    "docs",
    "doc",
    "documentation",
    "examples",
    "fixtures",
    "samples",
    "test",
    "tests",
    "tools",
    "vendor",
}


@dataclass
class InstallResult:
    project_root: Path
    project_id: str
    db_path: Path
    files_indexed: int
    symbols: int
    elapsed_s: float


def install(
    project_path: Path,
    *,
    verbose: bool = True,
    force_claude: bool = False,
    force_codex: bool = False,
    embed: bool = False,
    embed_limit: int | None = None,
) -> InstallResult:
    """Install ken into *project_path*.  Prints progress to stdout."""
    del force_claude  # Claude wiring is currently always enabled; flag is for CLI symmetry.
    if embed_limit is not None and embed_limit < 0:
        raise SystemExit("error: --embed-limit must be >= 0")
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

        # Step 4b: MCP server registration.
        _wire_mcp(root, verbose=verbose)

        # Step 4c: Codex CLI hooks + MCP. Same role as 4 + 4b for the
        # other CLI we support.
        _wire_codex(root, verbose=verbose, force=force_codex)

        # Step 5: initial index.
        if verbose:
            print("[index] walking project (respecting .gitignore)…")
        rels = list(iter_files(root))
        if verbose:
            print(f"[index] {len(rels)} candidate files; parsing…")
        embedder = None
        if embed:
            from ken.embedder import get_embedder

            if verbose:
                print("[index] embedding enabled; warming file + symbol embeddings…")
            embedder = get_embedder()

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

        if embedder is not None and embed_limit is not None and embed_limit < len(rels):
            embed_rels = _prioritize_embed_rels(rels)[:embed_limit]
            embed_set = set(embed_rels)
            rest = [rel for rel in rels if rel not in embed_set]
            if verbose:
                print(
                    f"[index] embedding limited to {len(embed_rels)} prioritized files; "
                    f"{len(rest)} files indexed structurally"
                )
            stats = index_files(conn, root, embed_rels, on_progress=progress, embedder=embedder)
            rest_stats = index_files(conn, root, rest, on_progress=progress, embedder=None)
            stats.visited += rest_stats.visited
            stats.parsed += rest_stats.parsed
            stats.unchanged += rest_stats.unchanged
            stats.skipped_no_lang += rest_stats.skipped_no_lang
            stats.skipped_too_large += rest_stats.skipped_too_large
            stats.skipped_io_error += rest_stats.skipped_io_error
            stats.symbols += rest_stats.symbols
            stats.imports += rest_stats.imports
            stats.elapsed_s += rest_stats.elapsed_s
        else:
            stats = index_files(conn, root, rels, on_progress=progress, embedder=embedder)
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
        print(f"        (Codex users: open {root} with `codex` and approve")
        print(f"         project trust, OR add `[projects.\"{root}\"]`")
        print(f"         `trust_level = \"trusted\"` to ~/.codex/config.toml)")

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


def _prioritize_embed_rels(rels: list[Path]) -> list[Path]:
    """Order files for bounded eager embedding.

    The goal is not perfect semantic selection; it is a cheap cold-start
    heuristic that spends the limited embedding budget on source files an
    agent is most likely to edit or inspect first.
    """
    return sorted(rels, key=_embed_priority_key)


def _embed_priority_key(rel: Path) -> tuple[int, int, int, str]:
    parts = {part.lower() for part in rel.parts}
    suffix = rel.suffix.lower()
    is_code = suffix in EMBED_PRIORITY_SUFFIXES
    low_priority = bool(parts & LOW_PRIORITY_PARTS)
    # Shorter source paths tend to be core modules; generated/vendor/docs
    # trees often sit deeper and are less useful for first-turn retrieval.
    return (
        0 if is_code else 1,
        1 if low_priority else 0,
        len(rel.parts),
        rel.as_posix(),
    )


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


def _wire_codex(root: Path, *, verbose: bool, force: bool = False) -> None:
    """Wire Codex CLI hooks (`.codex/hooks.json`) + MCP (`.codex/config.toml`).

    Project-local Codex hooks only fire if the user has marked the
    project as trusted in their user-level config — we print an
    instruction at the end of install rather than auto-editing
    ``~/.codex/config.toml``.
    """
    from ken.codex_hooks_template import (
        append_ken_mcp_block,
        has_ken_mcp_block,
        merge_codex_hooks,
        write_codex_hooks,
    )

    codex_dir = root / ".codex"
    _ensure_codex_dir(codex_dir, verbose=verbose, force=force)

    hooks_p = root / CODEX_HOOKS_FILE
    existing: dict | None = None
    if hooks_p.is_file():
        try:
            existing = json.loads(hooks_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if not force:
                print(
                    f"[codex] {hooks_p} is not valid JSON ({exc}); aborting",
                    file=sys.stderr,
                )
                raise SystemExit(2)
            if verbose:
                print(f"[codex] replacing invalid {CODEX_HOOKS_FILE} ({exc})")
            existing = None
    merged, touched = merge_codex_hooks(existing)
    write_codex_hooks(hooks_p, merged)
    if verbose:
        if touched:
            print(f"[codex] wired {', '.join(touched)} into {CODEX_HOOKS_FILE}")
        else:
            print(f"[codex] {CODEX_HOOKS_FILE} already had ken hooks — left alone")

    config_p = root / CODEX_CONFIG_FILE
    config_p.parent.mkdir(parents=True, exist_ok=True)
    cur_text = config_p.read_text(encoding="utf-8") if config_p.is_file() else ""
    if has_ken_mcp_block(cur_text):
        if verbose:
            print(
                f"[codex] {CODEX_CONFIG_FILE} already registers ken MCP — leaving alone"
            )
    else:
        config_p.write_text(append_ken_mcp_block(cur_text), encoding="utf-8")
        if verbose:
            print(f"[codex] registered `ken` MCP server in {CODEX_CONFIG_FILE}")


def _ensure_codex_dir(codex_dir: Path, *, verbose: bool, force: bool) -> None:
    if codex_dir.exists() and not codex_dir.is_dir():
        raise SystemExit(f"error: {codex_dir} exists and is not a directory")
    codex_dir.mkdir(parents=True, exist_ok=True)
    if not force:
        return
    mode = codex_dir.stat().st_mode
    if mode & stat.S_IWUSR:
        return
    codex_dir.chmod(mode | stat.S_IWUSR)
    if verbose:
        print("[codex] enabled owner write permission on .codex/")


def _wire_mcp(root: Path, *, verbose: bool) -> None:
    """Add ken's MCP server to the project's `.mcp.json`. Preserves any
    existing `mcpServers` entries — we only touch the `ken` key.
    """
    mcp_p = root / MCP_SETTINGS
    existing: dict = {}
    if mcp_p.is_file():
        try:
            existing = json.loads(mcp_p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"[mcp] {mcp_p} is not valid JSON ({exc}); aborting", file=sys.stderr
            )
            raise SystemExit(2)
    servers = existing.setdefault("mcpServers", {})
    desired = {"command": "ken", "args": ["mcp"]}
    if servers.get("ken") == desired:
        if verbose:
            print(f"[mcp] {MCP_SETTINGS} already registers ken — leaving alone")
        return
    servers["ken"] = desired
    mcp_p.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[mcp] registered `ken` MCP server in {MCP_SETTINGS}")


def _ken_version() -> str:
    from ken import __version__

    return __version__
