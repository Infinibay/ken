"""Session-start resume brief built from prior DB activity."""

from __future__ import annotations

import sqlite3

import pytest

from pathlib import Path

from ken.db import init_schema
from ken.session_brief import (
    _humanize_age,
    _relativize,
    _truncate,
    build_session_brief,
)

# A fixed "now" so age labels are deterministic.
NOW_MS = 1_000_000_000_000


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


def _session(conn, agent_id: str, started_at: int) -> int:
    cur = conn.execute(
        "INSERT INTO cr_sessions(agent_id, started_at) VALUES (?, ?)",
        (agent_id, started_at),
    )
    return int(cur.lastrowid)


def _context(conn, session_id: int, kind: str, content: str, created_at: int) -> None:
    conn.execute(
        "INSERT INTO cr_contexts(session_id, kind, content, iteration, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, kind, content, 0, created_at),
    )


def _interaction(conn, session_id: int, event_type: str, path: str, created_at: int) -> None:
    conn.execute(
        "INSERT INTO cr_interactions(session_id, iteration, event_type, target_kind, "
        "target_path, weight, created_at) VALUES (?, ?, ?, 'file', ?, 1.0, ?)",
        (session_id, 0, event_type, path, created_at),
    )


def _finding(conn, topic: str, content: str, updated_at: int) -> None:
    conn.execute(
        "INSERT INTO cr_findings(topic, content, tags, created_at, updated_at) "
        "VALUES (?, ?, '[]', ?, ?)",
        (topic, content, updated_at, updated_at),
    )


# ── empty / degenerate cases ───────────────────────────────────────


def test_empty_db_returns_empty_string(conn):
    assert build_session_brief(conn, now_ms=NOW_MS) == ""


def test_session_without_prompt_and_no_findings_is_empty(conn):
    sid = _session(conn, "a", NOW_MS - 1000)
    _context(conn, sid, "turn_end", "did stuff", NOW_MS - 900)
    assert build_session_brief(conn, now_ms=NOW_MS) == ""


# ── findings-only ──────────────────────────────────────────────────


def test_findings_only_skips_last_session_block(conn):
    _finding(conn, "auth flow", "JWT lives in src/auth.py", NOW_MS - 5000)
    brief = build_session_brief(conn, now_ms=NOW_MS)
    assert "<ken-session-brief>" in brief
    assert "Última sesión" not in brief
    assert "Findings guardados (1 recientes)" in brief
    assert "auth flow" in brief


# ── full recap ─────────────────────────────────────────────────────


def test_full_recap_includes_task_narrative_files_and_findings(conn):
    sid = _session(conn, "a", NOW_MS - 7_200_000)  # ~2h ago
    _context(conn, sid, "user_prompt", "fix the session start hook", NOW_MS - 7_200_000)
    _context(conn, sid, "turn_end", "Wired the brief into the daemon.", NOW_MS - 7_000_000)
    _interaction(conn, sid, "read", "src/ken/hook.py", NOW_MS - 7_100_000)
    _interaction(conn, sid, "edit", "src/ken/daemon/server.py", NOW_MS - 7_050_000)
    _finding(conn, "hook injection", "SessionStart stdout is injected", NOW_MS - 6_000_000)

    brief = build_session_brief(conn, now_ms=NOW_MS)

    assert brief.startswith("<ken-session-brief>")
    assert brief.endswith("</ken-session-brief>")
    assert "Última sesión (hace ~2h):" in brief
    assert 'Tarea: "fix the session start hook"' in brief
    assert "Por dónde ibas:" in brief
    assert "Wired the brief into the daemon." in brief
    # Edit outranks read, so the edited file is listed first.
    files_line = next(ln for ln in brief.splitlines() if "Archivos en juego" in ln)
    assert files_line.index("server.py") < files_line.index("hook.py")
    assert "hook injection" in brief
    assert "ken_rank / ken_recall" in brief


def test_recap_anchors_on_most_recent_prompt_across_sessions(conn):
    old = _session(conn, "old", NOW_MS - 100_000)
    _context(conn, old, "user_prompt", "old task", NOW_MS - 100_000)
    new = _session(conn, "new", NOW_MS - 1000)
    _context(conn, new, "user_prompt", "newest task", NOW_MS - 1000)

    brief = build_session_brief(conn, now_ms=NOW_MS)
    assert "newest task" in brief
    assert "old task" not in brief


def test_freshly_created_empty_session_recaps_previous(conn):
    """A brand-new startup session (no prompts yet) must recap the prior one."""
    prev = _session(conn, "prev", NOW_MS - 50_000)
    _context(conn, prev, "user_prompt", "previous work", NOW_MS - 50_000)
    _session(conn, "fresh", NOW_MS)  # current session, no prompts

    brief = build_session_brief(conn, now_ms=NOW_MS)
    assert "previous work" in brief


def test_brief_is_capped(conn):
    sid = _session(conn, "a", NOW_MS - 1000)
    _context(conn, sid, "user_prompt", "x" * 5000, NOW_MS - 1000)
    brief = build_session_brief(conn, now_ms=NOW_MS)
    assert len(brief) <= 1800 + len("<ken-session-brief>\n\n…\n</ken-session-brief>")
    assert brief.endswith("</ken-session-brief>")


# ── helpers ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "delta_ms,expected",
    [
        (-5, ""),
        (10_000, "hace instantes"),
        (5 * 60_000, "hace ~5min"),
        (3 * 3_600_000, "hace ~3h"),
        (2 * 86_400_000, "hace ~2d"),
        (40 * 86_400_000, "hace tiempo"),
    ],
)
def test_humanize_age(delta_ms, expected):
    assert _humanize_age(delta_ms) == expected


def test_relativize_strips_project_root():
    root = Path("/home/u/proj")
    assert _relativize("/home/u/proj/src/a.py", root) == "src/a.py"
    # Already relative, or outside the root → unchanged.
    assert _relativize("src/a.py", root) == "src/a.py"
    assert _relativize("/etc/passwd", root) == "/etc/passwd"
    assert _relativize("/home/u/proj/src/a.py", None) == "/home/u/proj/src/a.py"


def test_recap_relativizes_touched_files(conn):
    sid = _session(conn, "a", NOW_MS - 1000)
    _context(conn, sid, "user_prompt", "task", NOW_MS - 1000)
    _interaction(conn, sid, "edit", "/home/u/proj/src/a.py", NOW_MS - 900)
    brief = build_session_brief(conn, project_root=Path("/home/u/proj"), now_ms=NOW_MS)
    assert "src/a.py" in brief
    assert "/home/u/proj" not in brief


def test_truncate_collapses_and_clips():
    assert _truncate("a   b\n c", 100) == "a b c"
    out = _truncate("word " * 100, 20)
    assert len(out) <= 20
    assert out.endswith("…")
