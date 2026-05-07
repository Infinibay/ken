"""DaemonState session bookkeeping (no HTTP layer involved)."""

from __future__ import annotations

import pytest

from ken.daemon.server import DaemonState


@pytest.fixture
def state(tmp_path):
    (tmp_path / ".ken").mkdir()
    st = DaemonState(tmp_path, auth_token="tok")
    yield st
    st.conn.close()


def test_session_start_inserts_and_returns_pk(state):
    pk = state.session_start("agent-1")
    assert pk > 0
    row = state.conn.execute(
        "SELECT id, agent_id FROM cr_sessions WHERE id = ?", (pk,)
    ).fetchone()
    assert row["agent_id"] == "agent-1"


def test_session_start_idempotent(state):
    """Repeated session_start for same agent_id returns the same pk."""
    pk1 = state.session_start("agent-1")
    pk2 = state.session_start("agent-1")
    assert pk1 == pk2
    # Single row in the DB.
    n = state.conn.execute(
        "SELECT COUNT(*) FROM cr_sessions WHERE agent_id = 'agent-1'"
    ).fetchone()[0]
    assert n == 1


def test_session_end_removes_from_active(state):
    state.session_start("agent-1")
    assert "agent-1" in state.sessions
    state.session_end("agent-1")
    assert "agent-1" not in state.sessions
    # ended_at column populated.
    row = state.conn.execute(
        "SELECT ended_at FROM cr_sessions WHERE agent_id = 'agent-1'"
    ).fetchone()
    assert row["ended_at"] is not None


def test_session_end_sets_empty_since_when_last(state):
    state.session_start("a")
    state.session_start("b")
    state.session_end("a")
    assert state.empty_since is None  # b still active
    state.session_end("b")
    assert state.empty_since is not None


def test_next_iteration_increments(state):
    state.session_start("a")
    pk1, it1 = state.next_iteration("a")
    pk2, it2 = state.next_iteration("a")
    assert pk1 == pk2
    assert it2 == it1 + 1


def test_next_iteration_lazy_creates_session(state):
    """If SessionStart was never called, next_iteration creates one."""
    pk, it = state.next_iteration("ghost")
    assert pk > 0
    assert it == 1
    assert "ghost" in state.sessions


def test_invalidate_last_interaction_drops_only_recent(state):
    state.session_start("a")
    # Two pre-tool reads of the same path → 2 rows.
    state.record_interaction("a", "read", "file", target_path="src/a.py")
    state.record_interaction("a", "read", "file", target_path="src/a.py")
    state.invalidate_last_interaction("a", "src/a.py")
    n = state.conn.execute(
        "SELECT COUNT(*) FROM cr_interactions WHERE target_path = 'src/a.py'"
    ).fetchone()[0]
    assert n == 1


def test_invalidate_last_interaction_no_session_is_noop(state):
    """Calling for an unknown agent_id shouldn't crash or touch DB."""
    state.invalidate_last_interaction("ghost", "src/a.py")  # no error
