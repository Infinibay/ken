"""Session-start resume brief.

The SessionStart hook prints this block to stdout so a fresh session
(new window, ``/clear``, or ``compact``) starts already knowing "where
you left off" — without the model having to call ``recall`` / ``rank``
first. That proactive step is exactly what models forget to do, so the
durable knowledge ken accumulates never surfaces. Injecting it
automatically removes the dependency on model cooperation.

Everything here comes from data already in the DB:

  * the most recent session's last ``user_prompt`` (the task),
  * that session's last ``turn_end`` text (what was happening),
  * the files it read / edited / cited (what was in play), and
  * the most recent saved findings (durable project knowledge).

Anchoring on "the most recent prompt anywhere" is what makes this
robust across the SessionStart matchers: on a fresh ``startup`` the
just-created session has no prompts yet, so the anchor is the previous
session; on ``/clear`` / ``compact`` the DB is untouched, so the anchor
is the in-flight session whose model context was just wiped. Both mean
"where you left off".
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

# Tighter than the /prompts injection (3500): a resume brief is a nudge,
# not the working context. Keep it skimmable.
BRIEF_MAX_CHARS = 1800

_TASK_MAX = 200
_NARRATIVE_MAX = 220
_FINDING_MAX = 140
_MAX_FILES = 5
_MAX_FINDINGS = 3


def build_session_brief(
    conn: sqlite3.Connection,
    *,
    project_root: Path | None = None,
    now_ms: int | None = None,
) -> str:
    """Return a ``<ken-session-brief>`` block, or ``""`` when there's
    nothing worth injecting (first-ever session, empty DB).

    ``project_root`` is used only to relativise file paths for display —
    tool hooks record absolute paths, which read as noise in the brief.
    """
    from ken.memory import list_findings

    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    anchor = _latest_prompt(conn)
    findings = list_findings(conn, limit=_MAX_FINDINGS)

    if anchor is None and not findings:
        return ""

    lines: list[str] = [
        "Reanudando en este proyecto — contexto de ken (no hace falta recall):",
    ]

    if anchor is not None:
        age = _humanize_age(now_ms - anchor["created_at"])
        lines.append("")
        lines.append(f"Última sesión ({age}):" if age else "Última sesión:")
        lines.append(f'  • Tarea: "{_truncate(anchor["prompt"], _TASK_MAX)}"')
        narrative = _last_turn_narrative(conn, anchor["session_id"])
        if narrative:
            lines.append(f'  • Por dónde ibas: "{_truncate(narrative, _NARRATIVE_MAX)}"')
        files = _touched_files(conn, anchor["session_id"])
        if files:
            shown = [_relativize(p, project_root) for p in files]
            lines.append(f"  • Archivos en juego: {', '.join(shown)}")

    if findings:
        lines.append("")
        lines.append(f"Findings guardados ({len(findings)} recientes):")
        for f in findings:
            lines.append(f"  • {f['topic']} — {_truncate(f['content'], _FINDING_MAX)}")

    lines.append("")
    lines.append("Profundizá con ken_rank / ken_recall si seguís en esta tarea.")

    inner = "\n".join(lines)
    if len(inner) > BRIEF_MAX_CHARS:
        inner = inner[:BRIEF_MAX_CHARS].rstrip() + "\n…"
    return f"<ken-session-brief>\n{inner}\n</ken-session-brief>"


def _latest_prompt(conn: sqlite3.Connection) -> dict | None:
    """Most recent non-empty user prompt across all sessions."""
    row = conn.execute(
        """
        SELECT session_id, content, created_at
        FROM cr_contexts
        WHERE kind = 'user_prompt' AND content <> ''
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return {
        "session_id": int(row["session_id"]),
        "prompt": row["content"],
        "created_at": int(row["created_at"]),
    }


def _last_turn_narrative(conn: sqlite3.Connection, session_id: int) -> str:
    """The assistant's last reply for the anchor session, if any."""
    row = conn.execute(
        """
        SELECT content
        FROM cr_contexts
        WHERE session_id = ? AND kind = 'turn_end' AND content <> ''
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    return row["content"] if row is not None else ""


def _touched_files(conn: sqlite3.Connection, session_id: int) -> list[str]:
    """Files the anchor session worked on, ranked edit > cited > read.

    Aggregating ``cr_interactions`` directly (rather than
    ``cr_session_scores``) is deliberate: scores are only snapshotted on
    SessionEnd, so a ``/clear`` mid-session would have none — the raw
    interactions are always present.
    """
    rows = conn.execute(
        """
        SELECT target_path,
               SUM(CASE event_type
                       WHEN 'edit' THEN 3
                       WHEN 'cited' THEN 2
                       WHEN 'read' THEN 1
                       ELSE 0 END) AS score,
               MAX(created_at) AS last_at
        FROM cr_interactions
        WHERE session_id = ? AND target_path IS NOT NULL AND target_path <> ''
        GROUP BY target_path
        ORDER BY score DESC, last_at DESC
        LIMIT ?
        """,
        (session_id, _MAX_FILES),
    ).fetchall()
    return [r["target_path"] for r in rows if r["score"]]


def _humanize_age(delta_ms: int) -> str:
    """Coarse, human "hace ~Nh" label. Empty for negative deltas."""
    if delta_ms < 0:
        return ""
    minutes = delta_ms / 60_000
    if minutes < 1:
        return "hace instantes"
    if minutes < 60:
        return f"hace ~{int(minutes)}min"
    hours = minutes / 60
    if hours < 24:
        return f"hace ~{int(hours)}h"
    days = hours / 24
    if days < 30:
        return f"hace ~{int(days)}d"
    return "hace tiempo"


def _relativize(path: str, project_root: Path | None) -> str:
    """Strip the project-root prefix from an absolute tool path.

    Returns *path* unchanged when it's already relative or lives outside
    the project — a robust display tweak, never a correctness concern.
    """
    if project_root is None or not path.startswith("/"):
        return path
    try:
        return Path(path).relative_to(project_root).as_posix()
    except ValueError:
        return path


def _truncate(text: str, n: int) -> str:
    """Collapse whitespace and clip to ``n`` chars with an ellipsis."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    return text[: max(1, n - 1)].rstrip() + "…"


__all__ = ["build_session_brief"]
