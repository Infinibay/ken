"""Upgrade-safe model resolution + backend routing + the session-brief nudge."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from ken.db import init_schema, set_meta
from ken.embedder import (
    LEGACY_MODEL,
    RECOMMENDED_MODEL,
    configure_for_project,
    pending_upgrade,
    reset_embedder,
    resolve_model,
)
from ken.embedder import onnx_fastembed  # noqa: F401  (ensures package import)
import ken.embedder as emb


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("KEN_EMBED_MODEL", raising=False)
    reset_embedder()
    yield
    reset_embedder()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_schema(c)
    return c


def _add_embedded_file(conn, path="a.py"):
    conn.execute(
        "INSERT INTO ci_files(path, content_hash, embedding, mtime, indexed_at) "
        "VALUES (?, ?, ?, 0, 0)",
        (path, b"h", np.ones(4, dtype=np.float32).tobytes()),
    )


# ── resolve_model ────────────────────────────────────────────────────

def test_fresh_db_resolves_recommended(conn):
    assert resolve_model(conn) == RECOMMENDED_MODEL


def test_legacy_db_without_meta_infers_legacy(conn):
    # A DB that already holds vectors but predates model-recording was built
    # with the old default — never silently switch it.
    _add_embedded_file(conn)
    assert resolve_model(conn) == LEGACY_MODEL


def test_recorded_model_wins(conn):
    _add_embedded_file(conn)
    set_meta(conn, "embed_model", "some/custom-model")
    assert resolve_model(conn) == "some/custom-model"


def test_env_override_wins(conn, monkeypatch):
    _add_embedded_file(conn)
    set_meta(conn, "embed_model", "some/custom-model")
    monkeypatch.setenv("KEN_EMBED_MODEL", "env/model")
    assert resolve_model(conn) == "env/model"


# ── configure_for_project (records only fresh DBs) ───────────────────

def test_configure_records_recommended_for_fresh_db(conn):
    from ken.db import get_meta

    model = configure_for_project(conn)
    assert model == RECOMMENDED_MODEL
    assert get_meta(conn, "embed_model") == RECOMMENDED_MODEL  # pinned


def test_configure_does_not_touch_legacy_db(conn):
    from ken.db import get_meta

    _add_embedded_file(conn)
    model = configure_for_project(conn)
    assert model == LEGACY_MODEL
    # a legacy DB is left inferred, not rewritten
    assert get_meta(conn, "embed_model") is None


# ── pending_upgrade ──────────────────────────────────────────────────

def test_pending_upgrade_only_for_legacy(conn):
    _add_embedded_file(conn)
    assert pending_upgrade(conn) == (LEGACY_MODEL, RECOMMENDED_MODEL)


def test_no_upgrade_when_on_recommended(conn):
    set_meta(conn, "embed_model", RECOMMENDED_MODEL)
    assert pending_upgrade(conn) is None


def test_no_upgrade_for_custom_better_model(conn):
    # A user who moved to a stronger torch model must not be nagged to "downgrade".
    _add_embedded_file(conn)
    set_meta(conn, "embed_model", "Qwen/Qwen3-Embedding-0.6B")
    assert pending_upgrade(conn) is None


def test_env_override_silences_upgrade(conn, monkeypatch):
    _add_embedded_file(conn)
    monkeypatch.setenv("KEN_EMBED_MODEL", LEGACY_MODEL)
    assert pending_upgrade(conn) is None


# ── backend routing ──────────────────────────────────────────────────

def test_fastembed_model_detected():
    assert emb._is_fastembed_model(LEGACY_MODEL) is True
    assert emb._is_fastembed_model(RECOMMENDED_MODEL) is True
    assert emb._is_fastembed_model("Qwen/Qwen3-Embedding-0.6B") is False


def test_torch_model_without_backend_raises_helpful_error(monkeypatch):
    # Simulate sentence-transformers not installed: find_spec returns None.
    import importlib.util

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        if name == "sentence_transformers":
            return None
        return real_find_spec(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    with pytest.raises(RuntimeError, match=r"ken-rank\[torch\]"):
        emb._build_backend("Qwen/Qwen3-Embedding-0.6B")


# ── session-brief upgrade nudge ──────────────────────────────────────

def test_session_brief_surfaces_upgrade_then_throttles(conn):
    from ken.session_brief import build_session_brief

    _add_embedded_file(conn)  # legacy DB → upgrade pending
    conn.execute(
        "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('a', 0)"
    )
    conn.execute(
        "INSERT INTO cr_contexts(session_id, kind, content, iteration, created_at) "
        "VALUES (1, 'user_prompt', 'fix the parser', 0, 1000)"
    )
    now = 10_000_000
    first = build_session_brief(conn, now_ms=now)
    assert "ken reembed --model" in first
    assert RECOMMENDED_MODEL in first

    # within the throttle window → no repeat
    second = build_session_brief(conn, now_ms=now + 1000)
    assert "ken reembed --model" not in second

    # a week later → resurfaces
    later = build_session_brief(conn, now_ms=now + 8 * 24 * 3600 * 1000)
    assert "ken reembed --model" in later
