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

import re
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
        "Likely relevant resources.",
    ]
    outline_rows: list[tuple[str, list[str]]] = []
    if result.files:
        lines.append("")
        lines.append("Files (by relevance):")
        for i, it in enumerate(result.files[:max_files], 1):
            priority = _file_priority(i)
            channels = _channel_summary(it.reason, item_type="file")
            lines.append(
                f"  {i}. {it.target}  [{priority}; score={it.score:.1f}; {channels}] — {it.reason}"
            )
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
            kind = _finding_kind(it.tags, it.topic, it.content)
            channels = _channel_summary(it.reason, item_type="finding")
            lines.append(
                f"  {i}. {it.topic}{tags}  [type={kind}; score={it.score:.1f}; {channels}] — {it.reason}"
            )
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
        SELECT s.kind, s.name, s.qualname, s.line_start, s.docstring
        FROM ci_symbols s
        JOIN ci_files f ON f.id = s.file_id
        WHERE f.path = ?
        ORDER BY s.line_start
        LIMIT ?
        """,
        (path, limit),
    ).fetchall()
    out: list[str] = []
    for r in rows:
        line = f"{r['kind']} {r['qualname']} (line {r['line_start']})"
        doc = _one_line(str(r["docstring"] or ""), limit=96)
        if doc:
            line = f"{line} — {doc}"
        out.append(line)
    return out


def _file_priority(index: int) -> str:
    if index == 1:
        return "open-first"
    if index <= 3:
        return "open-early"
    return "secondary"


def _channel_summary(reason: str, *, item_type: str) -> str:
    semantic = 0.0
    recentness = 0.0
    dependency = 0.0
    finding = 0.0

    for value in re.findall(r"fuzzy:([0-9.]+)", reason):
        semantic = max(semantic, float(value))
    for value in re.findall(r"doc-intent(?:-symbol)?:[^:|+]+:([0-9.]+)", reason):
        semantic = max(semantic, float(value))
    if "explicit-mention" in reason or "explicit-symbol-mention" in reason:
        semantic = max(semantic, 1.0)
    if "explicit-line-mention" in reason:
        semantic = max(semantic, 0.9)
    if "lexical" in reason:
        semantic = max(semantic, 0.6)
    if "reactive:" in reason or "predictive" in reason:
        semantic = max(semantic, 0.5)

    fresh = re.search(r"fresh×([0-9.]+)", reason)
    if fresh:
        recentness = max(0.0, float(fresh.group(1)) - 1.0)

    for value in re.findall(r"(?:symbol-file|import-affinity|test-affinity|cooc)\+([0-9.]+)", reason):
        dependency += float(value)
    if any(marker in reason for marker in ("symbol-file(", "import-affinity(", "test-affinity(", "cooc(")):
        dependency = max(dependency, 0.4)

    finding_match = re.search(r"finding:([0-9.]+)", reason)
    if finding_match:
        finding = float(finding_match.group(1))
    elif item_type == "finding":
        finding = 1.0

    return (
        f"semantic_relevance={semantic:.2f}, "
        f"recentness={recentness:.2f}, "
        f"dependency_affinity={dependency:.1f}, "
        f"remembered_finding={finding:.2f}"
    )


def _finding_kind(tags: list[str], topic: str, content: str) -> str:
    haystack = " ".join([topic, content, *tags]).lower()
    if "ken-rule" in haystack or "rule" in haystack or "objective" in haystack:
        return "persistent_rule"
    if "negative-result" in haystack or "bugfix" in haystack or "test" in haystack:
        return "experimental_finding"
    if "hypothesis" in haystack or "research" in haystack:
        return "hypothesis"
    return "finding"


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
