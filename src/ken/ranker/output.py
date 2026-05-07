"""Render a ``RankResult`` into the ``<context-rank>`` block Claude
Code injects ahead of the user prompt.

Three verbose levels — model picks when it wants more detail via the
``ken_rank`` MCP tool. Default (0) is intentionally terse so we don't
swamp the prompt budget with information the model didn't ask for.

Level 0 — terse (default for hook injection):

    <context-rank>
    Relevant context:
    Files:
    - src/auth.py
    - src/payments.py
    - tests/test_auth.py
    </context-rank>

Level 1 — medium: top 5 files + symbols/findings sections + 3-line outline.
Level 2 — full: top 8 files + symbols/findings sections + 12-line outlines.
"""

from __future__ import annotations

import sqlite3

from ken.ranker import RankResult

# Per-level caps. Tuple is (max_files, outline_per_file, max_symbols, max_findings).
# Even at verbose=0 we surface up to 2 ranked symbols — explicit-mention
# symbols often outrank everything and are exactly what the model needs
# for targeted prompts ("what does Session.expire do?").
_LEVEL_CAPS: dict[int, tuple[int, int, int, int]] = {
    0: (3, 0, 2, 1),
    1: (5, 3, 5, 3),
    2: (8, 12, 5, 3),
}


def render_block(
    conn: sqlite3.Connection,
    result: RankResult,
    *,
    verbose: int = 0,
    max_chars: int | None = None,
) -> str:
    """Format *result* at the requested verbose level.

    Returns ``""`` when the result is empty, regardless of level — there
    is nothing to inject.
    """
    if result.empty:
        return ""
    level = verbose if verbose in _LEVEL_CAPS else 1
    max_files, outline_n, max_symbols, max_findings = _LEVEL_CAPS[level]

    if level == 0:
        block = _render_terse(result, max_files, max_symbols, max_findings)
    else:
        block = _render_verbose(
            conn, result, max_files, outline_n, max_symbols, max_findings, level
        )
    return _fit_block(block, max_chars=max_chars)


def _render_terse(
    result: RankResult, max_files: int, max_symbols: int, max_findings: int
) -> str:
    lines = ["<context-rank>", "Relevant context:"]
    if result.files:
        lines.append("Files:")
        for it in result.files[:max_files]:
            lines.append(f"- {it.target}")
    if max_symbols and result.symbols:
        lines.append("Symbols:")
        for it in result.symbols[:max_symbols]:
            lines.append(f"- {it.target}")
    if max_findings and result.findings:
        lines.append("Notes:")
        for it in result.findings[:max_findings]:
            lines.append(f"- {it.topic}")
    lines.append("</context-rank>")
    return "\n".join(lines)


def _render_verbose(
    conn: sqlite3.Connection,
    result: RankResult,
    max_files: int,
    outline_n: int,
    max_symbols: int,
    max_findings: int,
    level: int,
) -> str:
    lines: list[str] = [
        f"<context-rank verbose={level}>",
        "Based on your current task and past sessions, these resources are likely relevant.",
    ]
    outline_rows: list[tuple[str, list[str]]] = []
    if result.files:
        lines.append("")
        lines.append("Files (by relevance):")
        for i, it in enumerate(result.files[:max_files], 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")
            if outline_n:
                outline = _file_outline(conn, it.target, outline_n)
                if outline:
                    outline_rows.append((it.target, outline))
    if result.symbols and max_symbols:
        lines.append("")
        lines.append("Symbols:")
        for i, it in enumerate(result.symbols[:max_symbols], 1):
            lines.append(f"  {i}. {it.target}  [score={it.score:.1f}] — {it.reason}")
    if result.findings and max_findings:
        lines.append("")
        lines.append("Findings:")
        for i, it in enumerate(result.findings[:max_findings], 1):
            tags = f" [{' '.join(it.tags)}]" if it.tags else ""
            lines.append(f"  {i}. {it.topic}{tags}  [score={it.score:.1f}] — {it.reason}")
            lines.append(f"       {_one_line(it.content)}")
    if outline_rows:
        lines.append("")
        lines.append("Outlines:")
        for path, outline in outline_rows:
            lines.append(f"  {path}:")
            for outline_line in outline:
                lines.append(f"       {outline_line}")
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


def _one_line(text: str, *, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _fit_block(block: str, *, max_chars: int | None) -> str:
    """Keep block under a character budget by dropping whole interior lines."""
    if max_chars is None or max_chars <= 0 or len(block) <= max_chars:
        return block
    lines = block.splitlines()
    if len(lines) <= 2:
        return block[:max_chars]
    footer = "</context-rank>"
    if lines[-1] != footer:
        return block[:max_chars]
    if len("\n".join([lines[0], footer])) > max_chars:
        return ""
    marker = "(truncated by context budget; call ken_rank(verbose=2) to expand.)"
    if len("\n".join([lines[0], marker, footer])) > max_chars:
        marker = "(truncated)"
    if len("\n".join([lines[0], marker, footer])) > max_chars:
        return "\n".join([lines[0], footer])
    kept = [lines[0]]
    for line in lines[1:-1]:
        candidate = "\n".join([*kept, line, marker, footer])
        if len(candidate) > max_chars:
            break
        kept.append(line)
    return "\n".join([*kept, marker, footer])
