"""Direct semantic search over ken's code index."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from ken.embedder import blob_to_vec, get_embedder


def search_files(conn: sqlite3.Connection, query: str, limit: int = 8) -> list[dict]:
    """Return indexed files nearest to *query* by embedding cosine similarity."""
    q = _query_vec(query)
    rows = conn.execute(
        "SELECT id, path, language, embedding FROM ci_files WHERE embedding IS NOT NULL"
    ).fetchall()
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


def search_symbols(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
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


def _query_vec(query: str) -> np.ndarray:
    q = get_embedder().embed_query(query)
    return q / (np.linalg.norm(q) + 1e-12)


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
