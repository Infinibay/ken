"""Rank/explain MCP fallbacks when no hook-backed session is active."""

from __future__ import annotations

import time

import numpy as np
import pytest

from ken.daemon.server import (
    HOOK_CONTEXT_MAX_CHARS,
    DaemonState,
    _handle_explain,
    _handle_prompt,
    _handle_rank,
)
from ken.embedder import vec_to_blob


class FakeEmbedder:
    def embed_query(self, text: str) -> np.ndarray:
        v = np.zeros(384, dtype=np.float32)
        v[0] = 1.0
        return v


@pytest.fixture
def state(tmp_path):
    (tmp_path / ".ken").mkdir()
    st = DaemonState(tmp_path, auth_token="tok")
    yield st
    st.conn.close()


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())


def _index_file(st: DaemonState, path: str = "src/a.py") -> None:
    now_ms = int(time.time() * 1000)
    src = st.project_root / path
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("def indexed():\n    return 1\n", encoding="utf-8")
    st.conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES (?, 'python', ?, ?, ?, ?)",
        (path, b"\x00" * 32, int(time.time() * 1e9), now_ms, vec_to_blob(FakeEmbedder().embed_query(path))),
    )


def _stored_prompt(st: DaemonState, prompt: str) -> None:
    session_pk = st.session_start("codex-session")
    st.record_context("codex-session", "user_prompt", prompt, embed=True)
    st.session_end("codex-session")
    assert session_pk > 0


def test_rank_with_query_works_without_active_session(state):
    _index_file(state)

    out = _handle_rank(state, {"query": "please inspect src/a.py", "verbose": 0})

    assert out["ok"] is True
    assert out["files"] >= 1
    assert out["symbols"] >= 0
    assert out["findings"] >= 0
    assert out["context_chars"] == len(out["context_block"])
    assert out["context_est_tokens"] == (out["context_chars"] + 3) // 4
    assert "src/a.py" in out["context_block"]


def test_prompt_injection_uses_context_budget(state, monkeypatch):
    _index_file(state)
    state.session_start("codex-session")
    seen: dict[str, int | None] = {}

    def fake_render(_conn, _result, *, verbose=0, max_chars=None):
        seen["verbose"] = verbose
        seen["max_chars"] = max_chars
        return "<context-rank></context-rank>"

    monkeypatch.setattr("ken.ranker.output.render_block", fake_render)

    block = _handle_prompt(state, "codex-session", "please inspect src/a.py")

    assert block == "<context-rank></context-rank>"
    assert seen == {"verbose": 0, "max_chars": HOOK_CONTEXT_MAX_CHARS}


def test_rank_without_query_uses_latest_persisted_prompt(state):
    _index_file(state)
    _stored_prompt(state, "please inspect src/a.py")

    out = _handle_rank(state, {"verbose": 0})

    assert out["ok"] is True
    assert out["prompt"] == "please inspect src/a.py"
    assert "src/a.py" in out["context_block"]


def test_rank_respects_explicit_context_budget(state):
    _index_file(state)

    out = _handle_rank(
        state,
        {"query": "please inspect src/a.py", "verbose": 2, "max_chars": 110},
    )

    assert out["ok"] is True
    assert out["context_chars"] <= 110
    assert out["context_block"].endswith("</context-rank>")


def test_explain_with_query_works_without_active_session(state):
    _index_file(state)

    out = _handle_explain(state, {"query": "please inspect src/a.py"})

    assert out["ok"] is True
    assert out["prompt"] == "please inspect src/a.py"
    assert out["channels"]["explicit_files"][0]["target"] == "src/a.py"


def test_explain_without_query_uses_latest_persisted_prompt(state):
    _index_file(state)
    _stored_prompt(state, "please inspect src/a.py")

    out = _handle_explain(state, {})

    assert out["ok"] is True
    assert out["prompt"] == "please inspect src/a.py"
