"""Direct semantic search over ken's code index."""

from __future__ import annotations

import re
import sqlite3
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

from ken.embedder import cosine_against, get_embedder, stack_embeddings


def search_files(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 8,
    *,
    project_root: Path | None = None,
) -> list[dict]:
    """Return indexed files matching *query*.

    Ordered by embedding cosine similarity, fused with a literal path/stem
    match when the query is a bare identifier. ``score`` is always the cosine.
    """
    q = _query_vec(query)
    scored = _scored_from_store(
        conn, "ci_files", q,
        "SELECT vec_slot, id, path, language FROM ci_files "
        "WHERE vec_slot IN ({placeholders})",
        "path", project_root,
    )
    if scored is None:
        rows = conn.execute(
            "SELECT id, path, language, embedding FROM ci_files WHERE embedding IS NOT NULL"
        ).fetchall()
        rows = _filter_live_rows(rows, "path", project_root)
        scored = _score_rows(q, rows)
    ranked = _fuse_literal(
        scored,
        _identifier_query(query),
        lambda r: (Path(r["path"]).stem, Path(r["path"]).name, r["path"]),
        limit,
    )

    out: list[dict] = []
    for score, row, tier in ranked:
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
                **({"match": _MATCH_LABEL[tier]} if tier else {}),
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
    """Return indexed symbols matching *query*.

    Ordered by embedding cosine similarity, fused with a literal name match
    when the query is a bare identifier. ``score`` is always the cosine.
    """
    q = _query_vec(query)
    scored = _scored_from_store(
        conn, "ci_symbols", q,
        "SELECT s.vec_slot, s.kind, s.name, s.qualname, s.line_start, s.line_end, "
        "       s.docstring, f.path AS file_path "
        "FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id "
        "WHERE s.vec_slot IN ({placeholders})",
        "file_path", project_root,
    )
    if scored is None:
        rows = conn.execute(
            """
            SELECT s.kind, s.name, s.qualname, s.line_start, s.line_end,
                   s.docstring, s.embedding, f.path AS file_path
            FROM ci_symbols s JOIN ci_files f ON f.id = s.file_id
            WHERE s.embedding IS NOT NULL
            """
        ).fetchall()
        rows = _filter_live_rows(rows, "file_path", project_root)
        scored = _score_rows(q, rows)
    ranked = _fuse_literal(
        scored,
        _identifier_query(query),
        lambda r: (r["name"], r["qualname"]),
        limit,
    )
    return [
        {
            "qualname": r["qualname"],
            "kind": r["kind"],
            "file": r["file_path"],
            "line": int(r["line_start"]),
            "line_end": int(r["line_end"]),
            "docstring": r["docstring"],
            "score": round(float(score), 3),
            **({"match": _MATCH_LABEL[tier]} if tier else {}),
        }
        for score, r, tier in ranked
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
    edges: set[tuple[int, int, int]] = set()
    hit_cap = False

    while q:
        file_id, dist = q.popleft()
        if dist >= max_depth:
            continue
        for src, dst, line in _graph_edge_ids(conn, file_id):
            edges.add((src, dst, line))
            for candidate in (src, dst):
                if candidate in seen:
                    continue
                if len(seen) >= max_nodes:
                    hit_cap = True
                    continue
                seen.add(candidate)
                q.append((candidate, dist + 1))

    rows = conn.execute(
        "SELECT id, path, language, symbol_count FROM ci_files WHERE id IN (%s)"
        % ",".join("?" for _ in seen),
        tuple(seen),
    ).fetchall()
    path_by_id = {int(r["id"]): r["path"] for r in rows}
    nodes = [
        {
            "path": r["path"],
            "language": r["language"] or "text",
            "symbol_count": int(r["symbol_count"]),
        }
        for r in sorted(rows, key=lambda item: item["path"])
    ]
    # Only edges whose *both* endpoints made it into `nodes`. The node cap can
    # stop the frontier mid-expansion, and emitting an edge whose endpoint was
    # never added leaves the caller with a graph pointing at files it was not
    # given — malformed for anything that renders or traverses it.
    kept = sorted(
        (path_by_id[s], path_by_id[d], line)
        for s, d, line in edges
        if s in path_by_id and d in path_by_id
    )
    out = {
        "ok": True,
        "root": root_row["path"],
        "depth": max_depth,
        "nodes": nodes,
        "edges": [
            {"kind": "import", "from": src, "to": dst, "line": line}
            for src, dst, line in kept
        ],
    }
    omitted = len(edges) - len(kept)
    if hit_cap or omitted:
        out["truncated"] = {
            "node_limit": max_nodes,
            "edges_omitted": omitted,
            "note": "raise `limit` to see the rest of the neighbourhood",
        }
    return out


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


# Evidence weights. A file named by the ecosystem's test convention is the
# strongest signal available — it is what the test's author chose to say about
# what they were testing. Importing the target corroborates, but on its own it
# is weak: every test of a widely-imported module (db, config, cli) imports it.
_TEST_CONVENTION = 3.0
_TEST_NAME_TOKENS = 2.0
_TEST_IMPORTS = 1.0

# Tokens carried by the test-file convention itself, never by the subject.
_TEST_STOP_TOKENS = frozenset({"test", "tests", "spec", "specs", "it", "should"})

# Stems that name a file's *role*, not its subject. `src/a/__init__.py` and
# `tests/b/__init__.py` share a name and nothing else, so the weak token
# channel must not link them. The convention channel is unaffected:
# `test_utils.py` is still the test for `utils.py`.
_STRUCTURAL_STEMS = frozenset({
    "__init__", "__main__", "index", "main", "mod", "app", "lib", "setup",
    "types", "utils", "helpers", "common", "base", "core", "conftest",
})

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def _name_tokens(text: str) -> set[str]:
    """Lowercase word tokens of a file name, splitting camelCase too."""
    spaced = _CAMEL_BOUNDARY.sub(" ", text)
    return {t for t in _NON_WORD.split(spaced.lower()) if t}


def _test_basename(path: str) -> str:
    """File name minus its final extension (``cli.test.ts`` -> ``cli.test``).

    Case is preserved: ``_name_tokens`` splits on camelCase, so lowercasing
    here would collapse ``UserServiceIntegrationTest`` into one token and
    silently disable token matching for every Java/C#/Kotlin test.
    """
    name = Path(path).name
    suffix = Path(name).suffix
    return name[: -len(suffix)] if suffix else name


def _conventional_test_names(stem: str) -> set[str]:
    """Test-file base names that conventionally belong to a source *stem*.

    Covers the layouts ken indexes: ``test_x`` / ``x_test`` (python, go, rust),
    ``x.test`` / ``x.spec`` (js, ts), ``XTest`` / ``XTests`` (java, c#), and
    ``x_spec`` (ruby).
    """
    s = stem.lower()
    return {
        f"test_{s}", f"{s}_test", f"{s}_spec",
        f"{s}.test", f"{s}.spec",
        f"{s}test", f"{s}tests", f"{s}spec",
    }


def _find_tests_for_row(conn: sqlite3.Connection, row: sqlite3.Row, *, limit: int) -> list[dict]:
    """Likely tests for a file, strongest evidence first.

    Every channel contributes to the same candidate rather than the first one
    winning, and the result is ranked — otherwise the one file actually named
    after the target sits wherever insertion order happened to put it, behind
    every test that merely imports it.
    """
    stem = Path(row["path"]).stem
    conventional = _conventional_test_names(stem)
    stem_tokens = (
        set() if stem.lower() in _STRUCTURAL_STEMS
        else _name_tokens(stem) - _TEST_STOP_TOKENS
    )

    scores: dict[str, float] = defaultdict(float)
    reasons: dict[str, list[str]] = defaultdict(list)

    for importer in _importers_for_file(conn, int(row["id"])):
        if _looks_like_test(importer["path"]):
            scores[importer["path"]] += _TEST_IMPORTS
            reasons[importer["path"]].append("imports target")

    # Narrow in SQL first: a repo's test files are a small slice of the index,
    # and this runs once per changed file in `changed_context`.
    rows = conn.execute(
        "SELECT path FROM ci_files WHERE path LIKE '%test%' OR path LIKE '%spec%' "
        "ORDER BY path"
    ).fetchall()
    for candidate in rows:
        path = candidate["path"]
        if not _looks_like_test(path):
            continue
        base = _test_basename(path)
        if base.lower() in conventional:
            scores[path] += _TEST_CONVENTION
            reasons[path].append("named for target")
        elif stem_tokens and stem_tokens <= (_name_tokens(base) - _TEST_STOP_TOKENS):
            # Token containment, not substring: `cli` must not match
            # `test_client`, and `index_queue` must still match
            # `test_index_queue`.
            scores[path] += _TEST_NAME_TOKENS
            reasons[path].append("name match")

    ranked = sorted(scores, key=lambda p: (-scores[p], p))
    return [
        {"path": p, "reason": "; ".join(reasons[p]), "score": round(scores[p], 1)}
        for p in ranked[:limit]
    ]


# Suffixes marking a test file in the snake/dot-separated ecosystems. The
# separator is part of the token, so matching them lowercased is safe.
# Directory-level `test/`, `tests/`, `spec/` and a `test_` prefix are separate.
_TEST_SUFFIXES = (
    "_test.py", "_test.go", "_test.rs", "_test.ts", "_test.js", "_test.dart",
    "_spec.rb", "_spec.js", "_spec.ts",
    ".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".test.mjs",
    ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx", ".spec.mjs",
)

# Java / C# / Kotlin instead mark tests with a capitalised suffix on the type
# name (`UserServiceTest.java`), which must be matched **case-sensitively**: a
# lowercased `endswith("test.java")` also swallows `Latest.java`, `Contest.cs`,
# `protest.cs` and `Greatest.kt`, none of which are tests.
_CAMEL_TEST_EXTS = (".java", ".cs", ".kt", ".kts")
_CAMEL_TEST_NAME = re.compile(r"(?:Test|Tests|Spec|Specs)$")

_TEST_DIRS = frozenset({"test", "tests", "spec", "__tests__"})


def _looks_like_test(path: str) -> bool:
    """Whether *path* is a test file, by any convention ken indexes.

    Every branch keeps "test" or "spec" somewhere in the path, which is what
    makes the SQL prefilter in ``_find_tests_for_row`` a provable superset.
    """
    p = Path(path)
    if _TEST_DIRS & {part.lower() for part in p.parts}:
        return True
    raw = p.name
    lowered = raw.lower()
    if lowered.startswith("test_") or lowered.endswith(_TEST_SUFFIXES):
        return True
    suffix = p.suffix
    if suffix.lower() in _CAMEL_TEST_EXTS:
        return _CAMEL_TEST_NAME.search(raw[: -len(suffix)]) is not None
    return False


def _unique_paths(paths: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _graph_edge_ids(conn: sqlite3.Connection, file_id: int) -> list[tuple[int, int, int]]:
    """Resolved import edges touching *file_id*, as ``(from_id, to_id, line)``.

    Ids rather than paths: the caller resolves every path in one query at the
    end instead of looking each endpoint up per edge.
    """
    rows = conn.execute(
        """
        SELECT i.from_file_id AS src, i.to_file_id AS dst, i.line
        FROM ci_imports i
        WHERE i.to_file_id IS NOT NULL AND (i.from_file_id = ? OR i.to_file_id = ?)
        ORDER BY src, dst, i.line
        """,
        (file_id, file_id),
    ).fetchall()
    return [(int(r["src"]), int(r["dst"]), int(r["line"])) for r in rows]


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


#: These tools return a handful of results (`limit` defaults to 8 and 10), so
#: unlike the ranker's threshold channels they are honest top-K consumers and can
#: stop at a partition instead of sorting the whole corpus. The pool is kept far
#: wider than `limit` because `_fuse_literal` reorders afterwards using a literal
#: name match, and a result that ranks poorly on cosine can still win on that.
_SEARCH_POOL = 512


def _scored_from_store(
    conn: sqlite3.Connection,
    space: str,
    q: np.ndarray,
    resolve_sql: str,
    path_key: str,
    project_root: Path | None,
) -> list[tuple[float, sqlite3.Row]] | None:
    """Top-K by cosine, read from the mapped store. None means "no store".

    Returning None rather than an empty list matters: these are user-invoked
    tools, and "the store is not there" has to fall through to the inline column
    instead of silently answering "nothing matched".
    """
    from ken import vectors

    hit = vectors.live_scores(conn, space, q)
    if hit is None:
        return None
    slots, sims = hit
    if slots.size == 0:
        return []
    k = min(_SEARCH_POOL, sims.size)
    top = np.argpartition(sims, -k)[-k:]
    top = top[np.argsort(sims[top])[::-1]]

    ids = [int(s) for s in slots[top]]
    by_slot: dict[int, sqlite3.Row] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        placeholders = ",".join("?" * len(chunk))
        for row in conn.execute(resolve_sql.format(placeholders=placeholders), chunk):
            by_slot[int(row["vec_slot"])] = row

    out: list[tuple[float, sqlite3.Row]] = []
    root = project_root.resolve() if project_root is not None else None
    for idx in top:
        row = by_slot.get(int(slots[idx]))
        if row is None:
            continue  # slot freed since the scan
        if root is not None and not (root / row[path_key]).exists():
            continue
        out.append((float(sims[idx]), row))
    return out


def _score_rows(q: np.ndarray, rows: list[sqlite3.Row]) -> list[tuple[float, sqlite3.Row]]:
    """Every row scored by cosine, best first (no truncation)."""
    if not rows:
        return []
    # Drop rows written by a previous embedding model instead of letting numpy
    # fail on a ragged stack; a fully stale index raises EmbeddingSpaceMismatch,
    # which names `ken reembed` as the fix.
    mat, kept = stack_embeddings([r["embedding"] for r in rows], dim=int(q.shape[0]))
    if not kept:
        return []
    sims = cosine_against(q, mat)
    pairs = [(float(s), rows[i]) for s, i in zip(sims.tolist(), kept)]
    return sorted(pairs, key=lambda x: x[0], reverse=True)


def _rank_rows(
    q: np.ndarray, rows: list[sqlite3.Row], limit: int
) -> list[tuple[float, sqlite3.Row]]:
    return _score_rows(q, rows)[: max(1, limit)]


# ── Literal-name channel ─────────────────────────────────────────────
#
# A dense vector of a bare identifier is a weak signal: "blast_radius" embeds
# about as close to `test_blast_radius_reverse_reachability` as to the function
# itself, and the test wins on length alone. When the query *is* an identifier
# we therefore also rank by literal name match and fuse the two rankings.
#
# Fusion is reciprocal rank, not a weighted sum of scores: cosine magnitudes
# differ per embedding model, so anything added to them has to be retuned per
# model. Ranks do not.

_RRF_K = 60  # standard reciprocal-rank-fusion damping
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")

_MATCH_EXACT = 3
_MATCH_QUALIFIED = 2
_MATCH_TOKENS = 1


def _identifier_query(query: str) -> str | None:
    """The query as a bare identifier, or None if it reads as prose.

    A single word that happens to name nothing is harmless: the literal channel
    comes back empty and the fusion degenerates to the plain semantic order.
    """
    q = query.strip()
    if not q or len(q.split()) != 1:
        return None
    return q if _IDENTIFIER_RE.fullmatch(q) else None


def _literal_tier(ident: str, names: tuple[str, ...]) -> int:
    """How literally *ident* matches any of a row's names (0 = not at all)."""
    lowered = ident.lower()
    ident_tokens = _name_tokens(ident)
    best = 0
    for name in names:
        if not name:
            continue
        low = name.lower()
        if low == lowered:
            return _MATCH_EXACT
        if low.endswith("." + lowered):
            best = max(best, _MATCH_QUALIFIED)
        elif ident_tokens and ident_tokens <= _name_tokens(name):
            best = max(best, _MATCH_TOKENS)
    return best


def _fuse_literal(
    scored: list[tuple[float, sqlite3.Row]],
    ident: str | None,
    names_of,
    limit: int,
) -> list[tuple[float, sqlite3.Row, int]]:
    """Combine the semantic order with a literal-name order.

    Two regimes, because the two kinds of evidence are not interchangeable:

    * An **exact** name match is categorically decisive — if you typed
      ``blast_radius`` and a symbol is called exactly that, no cosine margin
      outranks it. Those are promoted, ordered among themselves by similarity.
    * **Partial** matches (a qualified name, shared tokens) genuinely trade off
      against semantic closeness, so they go through reciprocal rank fusion.
      Plain RRF cannot express the first case: swapping two items between the
      two lists leaves their fused scores exactly equal.

    Returns ``(cosine, row, match_tier)``; the cosine keeps its own meaning and
    is reported as-is, while the *ordering* reflects both channels.
    """
    if ident is None:
        return [(s, r, 0) for s, r in scored[: max(1, limit)]]
    tiers = [_literal_tier(ident, names_of(r)) for _, r in scored]
    if not any(tiers):
        return [(s, r, 0) for s, r in scored[: max(1, limit)]]

    # `scored` is in semantic order, so an index doubles as its dense rank.
    exact = [i for i, tier in enumerate(tiers) if tier == _MATCH_EXACT]
    exact_set = set(exact)

    fused: dict[int, float] = {
        i: 1.0 / (_RRF_K + i + 1) for i in range(len(scored)) if i not in exact_set
    }
    partial = sorted(
        (i for i, tier in enumerate(tiers) if 0 < tier < _MATCH_EXACT),
        key=lambda i: (-tiers[i], i),
    )
    for rank, i in enumerate(partial):
        fused[i] += 1.0 / (_RRF_K + rank + 1)

    rest = sorted(fused, key=lambda i: (-fused[i], i))
    order = (exact + rest)[: max(1, limit)]
    return [(scored[i][0], scored[i][1], tiers[i]) for i in order]


_MATCH_LABEL = {
    _MATCH_EXACT: "exact",
    _MATCH_QUALIFIED: "qualified",
    _MATCH_TOKENS: "tokens",
}


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
