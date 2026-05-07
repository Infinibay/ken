"""Render a ``RankResult`` into the ``<context-rank>`` block Claude
Code injects ahead of the user prompt.

Three verbose levels — model picks when it wants more detail via the
``ken_rank`` MCP tool. Default (0) is intentionally terse so we don't
swamp the prompt budget with information the model didn't ask for.

Level 0 — terse (default for hook injection):

    <context-rank verbose=0>
    src/auth.py [5.2] reactive:read_edit
    src/payments.py [3.4] fuzzy:0.62
    tests/test_auth.py [2.8] cooc(3sess)
    (Call ken_rank(verbose=1|2) for outlines or to expand.)
    </context-rank>

Level 1 — medium: top 5 files + 3-line outline + symbols section.
Level 2 — full: top 8 files + 12-line outlines + symbols section.
"""

from __future__ import annotations

import sqlite3

from ken.ranker import RankResult

# Per-level caps. Tuple is (max_files, outline_per_file, max_symbols).
_LEVEL_CAPS: dict[int, tuple[int, int, int]] = {
    0: (3, 0, 0),
    1: (5, 3, 5),
    2: (8, 12, 5),
}


def render_block(conn: sqlite3.Connection, result: RankResult, *, verbose: int = 0) -> str:
    """Format *result* at the requested verbose level.

    Returns ``""`` when the result is empty, regardless of level — there
    is nothing to inject.
    """
    if result.empty:
        return ""
    level = verbose if verbose in _LEVEL_CAPS else 1
    max_files, outline_n, max_symbols = _LEVEL_CAPS[level]

    if level == 0:
        return _render_terse(result, max_files)
    return _render_verbose(conn, result, max_files, outline_n, max_symbols, level)


def _render_terse(result: RankResult, max_files: int) -> str:
    lines = ["<context-rank verbose=0>"]
    for it in result.files[:max_files]:
        lines.append(f"{it.target} [{it.score:.1f}] {it.reason}")
    lines.append("(Call ken_rank(verbose=1|2) for outlines or to expand.)")
    lines.append("</context-rank>")
    return "\n".join(lines)


def _render_verbose(
    conn: sqlite3.Connection,
    result: RankResult,
    max_files: int,
    outline_n: int,
    max_symbols: int,
    level: int,
) -> str:
    lines: list[str] = [
        f"<context-rank verbose={level}>",
        "Based on your current task and past sessions, these resources are likely relevant.",
    ]
    if result.files:
        lines.append("")
        lines.append("Files (by relevance):")
        for i, it in enumerate(result.files[:max_files], 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")
            if outline_n:
                for outline_line in _file_outline(conn, it.target, outline_n):
                    lines.append(f"       {outline_line}")
    if result.symbols and max_symbols:
        lines.append("")
        lines.append("Symbols:")
        for i, it in enumerate(result.symbols[:max_symbols], 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")
    lines.append("</context-rank>")
    return "\n".join(lines)


def _file_outline(conn: sqlite3.Connection, path: str, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT s.kind, s.name, s.qualname, s.line_start
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE f.path = ?
        ORDER BY s.line_start
        LIMIT ?
        """,
        (path, limit),
    ).fetchall()
    return [f"{r['kind']} {r['qualname']} (line {r['line_start']})" for r in rows]
