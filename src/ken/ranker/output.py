"""Render a ``RankResult`` into the ``<context-rank>`` block Claude
Code injects ahead of the user prompt.

Format mirrors infinidev's:

    <context-rank>
    Based on your current task and past sessions, these resources are likely relevant.
    Symbol outlines are included so you can act on them directly.

    Files (by relevance):
      1. src/auth.py  [score=4.5] — fuzzy:0.65 + fresh×1.20
           function login (line 12)
           class Session (line 17)
           method Session.expire (line 22)

    Symbols:
      1. login (src/auth.py:12)  [score=4.7] — fuzzy:0.65
    </context-rank>
"""

from __future__ import annotations

import sqlite3

from ken.ranker import RankResult

# Per-file outline cap so we don't blow the prompt budget on a 200-symbol
# vendored file that happened to fuzzy-match.
MAX_OUTLINE_PER_FILE = 12


def render_block(conn: sqlite3.Connection, result: RankResult) -> str:
    """Return the formatted block, or ``""`` if there's nothing to inject."""
    if result.empty:
        return ""

    lines: list[str] = [
        "<context-rank>",
        "Based on your current task and past sessions, these resources are likely relevant.",
        "Symbol outlines are included so you can act on them directly.",
    ]

    if result.files:
        lines.append("")
        lines.append("Files (by relevance):")
        for i, it in enumerate(result.files, 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")
            for outline_line in _file_outline(conn, it.target):
                lines.append(f"       {outline_line}")

    if result.symbols:
        lines.append("")
        lines.append("Symbols:")
        for i, it in enumerate(result.symbols, 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")

    lines.append("</context-rank>")
    return "\n".join(lines)


def _file_outline(conn: sqlite3.Connection, path: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT s.kind, s.name, s.qualname, s.line_start
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE f.path = ?
        ORDER BY s.line_start
        LIMIT ?
        """,
        (path, MAX_OUTLINE_PER_FILE),
    ).fetchall()
    return [f"{r['kind']} {r['qualname']} (line {r['line_start']})" for r in rows]
