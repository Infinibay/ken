"""Literal + BM25 search over the worktree (ken_grep).

Two contracts:

* ``mode='literal'`` (primary) — exact substring match, scanned live from the
  worktree so it never lies relative to disk. Returns line-cited snippets.
* ``mode='bm25'`` — ranked relevance via a SQLite FTS5 index whose tokenizer
  **preserves identifier characters** (``_ . -``), so ``MY_ENV_VAR`` and
  ``os.path`` are findable. The index is kept fresh by comparing
  ``ci_fts_state.content_hash`` against each indexed file before querying.

This exposes the ranker's internal literal-content signal as a first-class
tool and removes the forced ripgrep fallback.
"""

from __future__ import annotations

from pathlib import Path

from ken.indexer import _hash

_MAX_FILE_BYTES = 1024 * 1024


def _sync_fts(conn, project_root: Path) -> None:
    """Bring the FTS5 mirror in line with the live worktree (incremental)."""
    root = project_root.resolve()
    indexed = {r["path"] for r in conn.execute("SELECT path FROM ci_files")}
    state = {r["path"]: r["content_hash"] for r in conn.execute(
        "SELECT path, content_hash FROM ci_fts_state")}

    with conn:
        # Drop FTS rows for paths no longer indexed.
        for gone in set(state) - indexed:
            conn.execute("DELETE FROM fts_files WHERE path = ?", (gone,))
            conn.execute("DELETE FROM ci_fts_state WHERE path = ?", (gone,))
        for path in indexed:
            full = root / path
            try:
                data = full.read_bytes()
            except OSError:
                continue
            if len(data) > _MAX_FILE_BYTES:
                continue
            h = _hash(data)
            if state.get(path) == h:
                continue
            body = data.decode("utf-8", errors="replace")
            conn.execute("DELETE FROM fts_files WHERE path = ?", (path,))
            conn.execute("INSERT INTO fts_files(path, body) VALUES (?, ?)", (path, body))
            conn.execute(
                "INSERT INTO ci_fts_state(path, content_hash) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET content_hash = excluded.content_hash",
                (path, h),
            )


def grep(
    conn,
    query: str,
    *,
    mode: str = "literal",
    language: str | None = None,
    limit: int = 20,
    project_root: Path | None = None,
) -> dict:
    """Search the worktree for *query*, literal (default) or BM25-ranked."""
    if project_root is None:
        return {"ok": False, "error": "project_root required"}
    if not query:
        return {"ok": False, "error": "empty query"}

    lang_paths: set[str] | None = None
    if language:
        lang_paths = {
            r["path"] for r in conn.execute(
                "SELECT path FROM ci_files WHERE language = ?", (language,))
        }

    if mode == "bm25":
        _sync_fts(conn, project_root)
        return _bm25(conn, query, lang_paths, limit)
    return _literal(conn, query, lang_paths, limit, project_root)


def _literal(conn, query, lang_paths, limit, project_root: Path) -> dict:
    root = project_root.resolve()
    paths = [r["path"] for r in conn.execute("SELECT path FROM ci_files ORDER BY path")]
    hits: list[dict] = []
    needle = query
    for path in paths:
        if lang_paths is not None and path not in lang_paths:
            continue
        full = root / path
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if needle not in text:
            continue
        matches = []
        for lineno, line in enumerate(text.splitlines(), 1):
            if needle in line:
                matches.append({"line": lineno, "text": line.strip()[:200]})
                if len(matches) >= 5:
                    break
        hits.append({"path": path, "count": text.count(needle), "snippets": matches})
        if len(hits) >= max(1, int(limit)):
            break
    hits.sort(key=lambda h: -h["count"])
    return {"ok": True, "mode": "literal", "query": query, "results": hits}


def _bm25(conn, query, lang_paths, limit) -> dict:
    # Build a tolerant FTS query: OR the bare terms so partial matches rank.
    terms = [t for t in _safe_terms(query) if t]
    if not terms:
        return {"ok": True, "mode": "bm25", "query": query, "results": []}
    match = " OR ".join(terms)
    try:
        rows = conn.execute(
            """
            SELECT path, snippet(fts_files, 1, '[', ']', ' … ', 12) AS snip,
                   bm25(fts_files) AS score
            FROM fts_files
            WHERE fts_files MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (match, max(1, int(limit)) * 3),
        ).fetchall()
    except Exception as exc:  # pragma: no cover - malformed query
        return {"ok": False, "error": f"fts query failed: {exc}"}
    out = []
    for r in rows:
        if lang_paths is not None and r["path"] not in lang_paths:
            continue
        out.append({"path": r["path"], "score": round(float(r["score"]), 3),
                    "snippet": r["snip"]})
        if len(out) >= max(1, int(limit)):
            break
    return {"ok": True, "mode": "bm25", "query": query, "results": out}


def _safe_terms(query: str) -> list[str]:
    """Tokenise a query into FTS-safe terms (quote identifiers with . or -)."""
    raw = query.replace('"', " ").split()
    out = []
    for tok in raw:
        tok = tok.strip()
        if not tok:
            continue
        # Quote tokens containing FTS operator-ish characters.
        if any(c in tok for c in ".-_"):
            out.append(f'"{tok}"')
        else:
            out.append(tok)
    return out
