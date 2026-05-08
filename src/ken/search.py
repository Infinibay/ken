"""Direct semantic search over ken's code index."""

from __future__ import annotations

import subprocess
from collections import Counter, deque
import sqlite3
from pathlib import Path

import numpy as np

from ken.embedder import blob_to_vec, get_embedder


def search_files(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    *,
    project_root: Path | None = None,
) -> list[dict]:
    """Return indexed files nearest to *query* by embedding cosine similarity."""
    q = _query_vec(query)
    rows = conn.execute(
        "SELECT id, path, language, embedding FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchall()
    rows = _filter_live_rows(rows, "path", project_root)
    ranked = _rank_rows(q, rows, limit)

    out: list[dict] = []
    for score, row in ranked:
        outline_rows = conn.execute(
            "SELECT kind, name, line_start FROM ci_symbols "
            "WHERE file_id = ? ORDER BY line_start LIMIT 8",
            (int(row["id"]),),
        ).fetchall()
        out.append(
            {
                "path": row["path"],
                "language": row["language"] or "text",
                "score": round(float(score), 3),
                "symbols": [
                    {"kind": r["kind"], "name": r["name"], "line": int(r["line_start"])}
                    for r in outline_rows
                ],
            }
        )
    return out


def search_symbols(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    *,
    project_root: Path | None = None,
) -> list[dict]:
    """Return indexed symbols nearest to *query* by embedding cosine similarity."""
    q = _query_vec(query)
    rows = conn.execute(
        """
        SELECT s.kind, s.name, s.qualname, s.line_start, s.line_end,
               s.docstring, s.embedding, f.path AS file_path
        FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
        WHERE s.embedding IS NOT NULL
        """
    ).fetchall()
    rows = _filter_live_rows(rows, "file_path", project_root)
    return [
        {
            "qualname": r["qualname"],
            "kind": r["kind"],
            "file": r["file_path"],
            "line": int(r["line_start"]),
            "line_end": int(r["line_end"]),
            "docstring": r["docstring"],
            "score": round(float(score), 3),
        }
        for score, r in _rank_rows(q, rows, limit)
    ]


def file_symbols(
    conn: sqlite3.Connection,
    path: str,
    *,
    include_docstrings: bool = True,
    project_root: Path | None = None,
) -> dict:
    """Return the indexed symbol outline for one file path."""
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}
    if project_root is not None and not (project_root.resolve() / row["path"]).exists():
        return {"ok": False, "error": "file missing on disk", "path": row["path"]}

    symbol_rows = conn.execute(
        """
        SELECT kind, name, qualname, line_start, line_end, docstring
        FROM ci_symbols
        WHERE file_id = ?
        ORDER BY line_start, line_end, name
        """,
        (int(row["id"]),),
    ).fetchall()
    symbols: list[dict] = []
    for sym in symbol_rows:
        item = {
            "kind": sym["kind"],
            "name": sym["name"],
            "qualname": sym["qualname"],
            "line": int(sym["line_start"]),
            "line_end": int(sym["line_end"]),
        }
        if include_docstrings:
            item["docstring"] = sym["docstring"]
        symbols.append(item)

    return {
        "ok": True,
        "path": row["path"],
        "language": row["language"] or "text",
        "symbols": symbols,
    }


def file_outline(
    conn: sqlite3.Connection,
    path: str,
    *,
    include_symbols: bool = True,
    include_imports: bool = True,
    include_docstrings: bool = True,
    project_root: Path | None = None,
) -> dict:
    """Return an indexed file's structural outline."""
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}
    out = {
        "ok": True,
        "path": row["path"],
        "language": row["language"] or "text",
        "symbol_count": int(row["symbol_count"]),
        "indexed_at": int(row["indexed_at"]),
    }
    module_doc = _module_docstring(conn, int(row["id"]))
    if include_docstrings:
        out["docstring"] = module_doc
    if include_symbols:
        out["symbols"] = file_symbols(
            conn,
            row["path"],
            include_docstrings=include_docstrings,
            project_root=project_root,
        ).get("symbols", [])
    if include_imports:
        out["imports"] = _imports_for_file(conn, int(row["id"]))
        out["imported_by"] = _importers_for_file(conn, int(row["id"]))
    return out


def file_neighbors(
    conn: sqlite3.Connection,
    path: str,
    *,
    limit: int = 20,
    project_root: Path | None = None,
) -> dict:
    """Return files most directly related to *path*."""
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}
    file_id = int(row["id"])
    imports = _imports_for_file(conn, file_id)
    imported_by = _importers_for_file(conn, file_id)
    tests = _find_tests_for_row(conn, row, limit=limit)
    return {
        "ok": True,
        "path": row["path"],
        "imports": imports[:limit],
        "imported_by": imported_by[:limit],
        "tests": tests[:limit],
        "neighbors": _unique_paths(
            [
                *(imp["path"] for imp in imports if imp.get("path")),
                *(imp["path"] for imp in imported_by if imp.get("path")),
                *(test["path"] for test in tests),
            ]
        )[:limit],
    }


def symbol_detail(
    conn: sqlite3.Connection,
    path: str,
    qualname: str,
    *,
    include_snippet: bool = False,
    project_root: Path | None = None,
) -> dict:
    """Return one symbol's indexed metadata, optionally with source text."""
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}
    sym = conn.execute(
        """
        SELECT kind, name, qualname, line_start, line_end, docstring
        FROM ci_symbols
        WHERE file_id = ? AND (qualname = ? OR name = ?)
        ORDER BY CASE WHEN qualname = ? THEN 0 ELSE 1 END, line_start
        LIMIT 1
        """,
        (int(row["id"]), qualname, qualname, qualname),
    ).fetchone()
    if sym is None:
        return {
            "ok": False,
            "error": "symbol not indexed",
            "path": row["path"],
            "qualname": qualname,
        }
    out = {
        "ok": True,
        "path": row["path"],
        "language": row["language"] or "text",
        "symbol": _symbol_dict(sym, include_docstring=True),
    }
    if include_snippet and project_root is not None:
        out["snippet"] = _read_line_range(
            project_root,
            row["path"],
            int(sym["line_start"]),
            int(sym["line_end"]),
        )
    return out


def module_graph(
    conn: sqlite3.Connection,
    path: str,
    *,
    depth: int = 1,
    limit: int = 100,
    project_root: Path | None = None,
) -> dict:
    """Return a bounded local import graph around one file."""
    normalized = _normalize_index_path(path, project_root=project_root)
    root_row = _file_row(conn, normalized)
    if root_row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}

    max_depth = max(0, int(depth))
    max_nodes = max(1, int(limit))
    seen: set[int] = {int(root_row["id"])}
    q: deque[tuple[int, int]] = deque([(int(root_row["id"]), 0)])
    edges: set[tuple[str, str, str, int]] = set()

    while q and len(seen) <= max_nodes:
        file_id, dist = q.popleft()
        if dist >= max_depth:
            continue
        for edge in _graph_edges(conn, file_id):
            edges.add(edge)
            for candidate in (edge[1], edge[2]):
                row = _file_row(conn, candidate)
                if row is None:
                    continue
                cand_id = int(row["id"])
                if cand_id not in seen and len(seen) < max_nodes:
                    seen.add(cand_id)
                    q.append((cand_id, dist + 1))

    rows = conn.execute(
        "SELECT id, path, language, symbol_count FROM ci_files WHERE id IN (%s)"
        % ",".join("?" for _ in seen),
        tuple(seen),
    ).fetchall()
    nodes = [
        {
            "path": r["path"],
            "language": r["language"] or "text",
            "symbol_count": int(r["symbol_count"]),
        }
        for r in sorted(rows, key=lambda item: item["path"])
    ]
    return {
        "ok": True,
        "root": root_row["path"],
        "depth": max_depth,
        "nodes": nodes,
        "edges": [
            {"kind": kind, "from": src, "to": dst, "line": line}
            for kind, src, dst, line in sorted(edges)
        ],
    }


def find_tests(
    conn: sqlite3.Connection,
    path: str,
    *,
    limit: int = 20,
    project_root: Path | None = None,
) -> dict:
    """Return likely tests for an indexed file."""
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}
    return {
        "ok": True,
        "path": row["path"],
        "tests": _find_tests_for_row(conn, row, limit=max(1, int(limit))),
    }


def changed_context(conn: sqlite3.Connection, project_root: Path) -> dict:
    """Return git worktree changes enriched with indexed symbol outlines."""
    root = project_root.resolve()
    status = _git_status(root)
    changed = []
    for item in status:
        path = item["path"]
        row = _file_row(conn, path)
        outline = None
        tests: list[dict] = []
        if row is not None:
            outline = file_symbols(conn, path, include_docstrings=False).get("symbols", [])[:8]
            tests = _find_tests_for_row(conn, row, limit=8)
        changed.append({**item, "indexed": row is not None, "symbols": outline or [], "tests": tests})
    return {"ok": True, "changed": changed}


def file_snippets(
    conn: sqlite3.Connection,
    path: str,
    *,
    symbols: list[str] | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 12000,
    project_root: Path | None = None,
) -> dict:
    """Return source snippets for selected symbols or a line range."""
    if project_root is None:
        return {"ok": False, "error": "project_root required"}
    normalized = _normalize_index_path(path, project_root=project_root)
    row = _file_row(conn, normalized)
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": normalized}

    ranges: list[tuple[str, int, int]] = []
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        rows = conn.execute(
            f"""
            SELECT name, qualname, line_start, line_end
            FROM ci_symbols
            WHERE file_id = ? AND (name IN ({placeholders}) OR qualname IN ({placeholders}))
            ORDER BY line_start, line_end, name
            """,
            (int(row["id"]), *symbols, *symbols),
        ).fetchall()
        ranges.extend(
            (
                sym["qualname"] or sym["name"],
                int(sym["line_start"]),
                int(sym["line_end"]),
            )
            for sym in rows
        )
    elif start_line is not None:
        start = max(1, int(start_line))
        end = max(start, int(end_line or start))
        ranges.append((f"{row['path']}:{start}-{end}", start, end))
    else:
        rows = conn.execute(
            """
            SELECT name, qualname, line_start, line_end
            FROM ci_symbols
            WHERE file_id = ?
            ORDER BY line_start, line_end, name
            LIMIT 8
            """,
            (int(row["id"]),),
        ).fetchall()
        ranges.extend(
            (
                sym["qualname"] or sym["name"],
                int(sym["line_start"]),
                int(sym["line_end"]),
            )
            for sym in rows
        )

    snippets = []
    budget = max(1, int(max_chars))
    used = 0
    for label, start, end in ranges:
        text = _read_line_range(project_root, row["path"], start, end)
        remaining = budget - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining]
        used += len(text)
        snippets.append({"label": label, "line": start, "line_end": end, "code": text})
    return {"ok": True, "path": row["path"], "snippets": snippets}


def project_overview(
    conn: sqlite3.Connection,
    *,
    depth: int = 2,
    limit: int = 20,
) -> dict:
    """Return a compact structural overview of the indexed project."""
    rows = conn.execute("SELECT path, language, symbol_count FROM ci_files").fetchall()
    languages = Counter((r["language"] or "text") for r in rows)
    dirs: Counter[str] = Counter()
    max_depth = max(1, int(depth))
    for row in rows:
        parts = Path(row["path"]).parts[:-1]
        if parts:
            dirs["/".join(parts[:max_depth])] += 1
    entrypoints = [
        r["path"]
        for r in rows
        if Path(r["path"]).name
        in {"main.py", "__main__.py", "cli.py", "server.py", "app.py", "index.ts", "index.js"}
    ][: max(1, int(limit))]
    top_symbol_files = sorted(
        rows,
        key=lambda r: (int(r["symbol_count"]), r["path"]),
        reverse=True,
    )[: max(1, int(limit))]
    return {
        "ok": True,
        "files": len(rows),
        "languages": dict(languages.most_common()),
        "top_dirs": [{"path": path, "files": count} for path, count in dirs.most_common(limit)],
        "entrypoints": entrypoints,
        "largest_symbol_files": [
            {"path": r["path"], "symbols": int(r["symbol_count"])}
            for r in top_symbol_files
        ],
    }


def _normalize_index_path(path: str, *, project_root: Path | None = None) -> str:
    normalized = Path(path).as_posix()
    if project_root is not None:
        p = Path(path)
        if p.is_absolute():
            try:
                normalized = p.resolve().relative_to(project_root.resolve()).as_posix()
            except (OSError, ValueError):
                pass
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _file_row(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, path, language, symbol_count, indexed_at FROM ci_files WHERE path = ?",
        (path,),
    ).fetchone()


def _symbol_dict(row: sqlite3.Row, *, include_docstring: bool) -> dict:
    out = {
        "kind": row["kind"],
        "name": row["name"],
        "qualname": row["qualname"],
        "line": int(row["line_start"]),
        "line_end": int(row["line_end"]),
    }
    if include_docstring:
        out["docstring"] = row["docstring"]
    return out


def _module_docstring(conn: sqlite3.Connection, file_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT text FROM ci_intent_sources
        WHERE file_id = ? AND symbol_id IS NULL AND source_kind = 'module_docstring'
        LIMIT 1
        """,
        (file_id,),
    ).fetchone()
    return None if row is None else row["text"]


def _imports_for_file(conn: sqlite3.Connection, file_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT i.to_module, i.line, f.path
        FROM ci_imports i
        LEFT JOIN ci_files f ON f.id = i.to_file_id
        WHERE i.from_file_id = ?
        ORDER BY i.line, i.to_module
        """,
        (file_id,),
    ).fetchall()
    return [
        {
            "module": r["to_module"],
            "path": r["path"],
            "line": int(r["line"]),
            "internal": r["path"] is not None,
        }
        for r in rows
    ]


def _importers_for_file(conn: sqlite3.Connection, file_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT src.path, src.language, i.to_module, i.line
        FROM ci_imports i
        JOIN ci_files src ON src.id = i.from_file_id
        WHERE i.to_file_id = ?
        ORDER BY src.path, i.line
        """,
        (file_id,),
    ).fetchall()
    return [
        {
            "path": r["path"],
            "language": r["language"] or "text",
            "module": r["to_module"],
            "line": int(r["line"]),
        }
        for r in rows
    ]


def _find_tests_for_row(conn: sqlite3.Connection, row: sqlite3.Row, *, limit: int) -> list[dict]:
    target_path = row["path"]
    target = Path(target_path)
    stem = target.stem
    candidates: dict[str, dict] = {}

    for importer in _importers_for_file(conn, int(row["id"])):
        if _looks_like_test(importer["path"]):
            candidates[importer["path"]] = {"path": importer["path"], "reason": "imports target"}

    rows = conn.execute(
        "SELECT path, language FROM ci_files ORDER BY path"
    ).fetchall()
    for candidate in rows:
        path = candidate["path"]
        if not _looks_like_test(path):
            continue
        name = Path(path).stem.lower()
        lowered = path.lower()
        target_stem = stem.lower()
        if (
            target_stem in name
            or name in {f"test_{target_stem}", f"{target_stem}_test"}
            or f"/test_{target_stem}" in lowered
            or f"/{target_stem}_test" in lowered
        ):
            candidates.setdefault(path, {"path": path, "reason": "name match"})

    return list(candidates.values())[:limit]


def _looks_like_test(path: str) -> bool:
    parts = [part.lower() for part in Path(path).parts]
    name = Path(path).name.lower()
    return (
        "test" in parts
        or "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith(".test.ts")
        or name.endswith(".test.tsx")
        or name.endswith(".test.js")
        or name.endswith(".spec.ts")
        or name.endswith(".spec.tsx")
        or name.endswith(".spec.js")
    )


def _unique_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _graph_edges(conn: sqlite3.Connection, file_id: int) -> list[tuple[str, str, str, int]]:
    rows = conn.execute(
        """
        SELECT src.path AS src, dst.path AS dst, i.line
        FROM ci_imports i
        JOIN ci_files src ON src.id = i.from_file_id
        JOIN ci_files dst ON dst.id = i.to_file_id
        WHERE i.from_file_id = ? OR i.to_file_id = ?
        ORDER BY src.path, dst.path, i.line
        """,
        (file_id, file_id),
    ).fetchall()
    return [("import", r["src"], r["dst"], int(r["line"])) for r in rows]


def _read_line_range(project_root: Path, rel_path: str, start: int, end: int) -> str:
    full = project_root.resolve() / rel_path
    try:
        lines = full.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    selected = lines[max(0, start - 1): max(start - 1, end)]
    return "\n".join(f"{line_no}: {line}" for line_no, line in enumerate(selected, start))


def _git_status(project_root: Path) -> list[dict]:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=project_root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        out.append({"status": status, "path": path})
    return out


def _query_vec(query: str) -> np.ndarray:
    q = get_embedder().embed_query(query)
    return q / (np.linalg.norm(q) + 1e-12)


def _filter_live_rows(
    rows: list[sqlite3.Row],
    path_key: str,
    project_root: Path | None,
) -> list[sqlite3.Row]:
    if project_root is None:
        return rows
    root = project_root.resolve()
    return [row for row in rows if (root / row[path_key]).exists()]


def _rank_rows(
    q: np.ndarray, rows: list[sqlite3.Row], limit: int
) -> list[tuple[float, sqlite3.Row]]:
    if not rows:
        return []
    mat = np.asarray([blob_to_vec(r["embedding"]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1) + 1e-12
    sims = (mat @ q) / norms
    return sorted(zip(sims.tolist(), rows), key=lambda x: x[0], reverse=True)[: max(1, limit)]


def format_file_hits(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        lines.append(f"{hit['score']:.3f}  {hit['path']}  ({hit['language']})")
        symbols = hit.get("symbols") or []
        if symbols:
            outline = ", ".join(
                f"{s['kind']} {s['name']}:{s['line']}" for s in symbols[:5]
            )
            lines.append(f"       {outline}")
    return "\n".join(lines)


def format_symbol_hits(hits: list[dict]) -> str:
    lines: list[str] = []
    for hit in hits:
        lines.append(
            f"{hit['score']:.3f}  {hit['file']}:{hit['line']}  "
            f"{hit['kind']} {hit['qualname'] or ''}".rstrip()
        )
        doc = (hit.get("docstring") or "").strip()
        if doc:
            lines.append(f"       {doc}")
    return "\n".join(lines)
