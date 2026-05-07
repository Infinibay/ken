"""Shared fixtures for ranker tests.

We don't want to load the real fastembed model in unit tests — it adds
hundreds of ms per test and hits the network on first run. Instead we
build a minimal in-memory SQLite DB matching the real schema and write
embeddings as plain numpy vectors directly into BLOB columns.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from ken.embedder import vec_to_blob

SCHEMA = (Path(__file__).resolve().parents[2] / "src/ken/schema.sql").read_text()


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


@pytest.fixture
def fake_emb() -> Callable[[str], np.ndarray]:
    """Deterministic 384-dim embedding from a string.

    Each call seeds numpy with the hash of the string and pulls one
    Gaussian sample. Two identical inputs → identical embedding;
    different inputs → uncorrelated. Good enough for testing similarity
    pipelines without loading a real model.
    """
    def emb(text: str) -> np.ndarray:
        rng = np.random.default_rng(abs(hash(text)) & 0xFFFF_FFFF)
        v = rng.normal(size=384).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-12)
    return emb


@pytest.fixture
def now_ms() -> int:
    return int(time.time() * 1000)


@pytest.fixture
def make_session(conn: sqlite3.Connection, now_ms: int):
    def _mk(agent_id: str = "test-session") -> int:
        cur = conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES (?, ?)",
            (agent_id, now_ms),
        )
        return int(cur.lastrowid)
    return _mk


@pytest.fixture
def make_file(conn: sqlite3.Connection, now_ms: int, fake_emb):
    """Insert a ci_files row with a deterministic embedding."""
    def _mk(path: str, *, language: str = "python", days_old: float = 0.0) -> int:
        mtime_ns = int(time.time() * 1e9 - days_old * 86_400 * 1e9)
        cur = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (path, language, b"\x00" * 32, mtime_ns, now_ms, vec_to_blob(fake_emb(path))),
        )
        return int(cur.lastrowid)
    return _mk


@pytest.fixture
def make_symbol(conn: sqlite3.Connection, fake_emb):
    def _mk(file_id: int, *, name: str, qualname: str | None = None,
            kind: str = "function", line_start: int = 1, line_end: int = 5) -> int:
        cur = conn.execute(
            "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, kind, name, qualname or name, line_start, line_end, vec_to_blob(fake_emb(name))),
        )
        return int(cur.lastrowid)
    return _mk


@pytest.fixture
def make_interaction(conn: sqlite3.Connection, now_ms: int):
    def _mk(session_id: int, *, event: str, target: str, iteration: int = 1,
            context_id: int | None = None, weight: float = 1.0) -> int:
        cur = conn.execute(
            "INSERT INTO cr_interactions(session_id, context_id, iteration, event_type, "
            "target_kind, target_path, weight, created_at) "
            "VALUES (?, ?, ?, ?, 'file', ?, ?, ?)",
            (session_id, context_id, iteration, event, target, weight, now_ms),
        )
        return int(cur.lastrowid)
    return _mk


@pytest.fixture
def make_prompt(conn: sqlite3.Connection, now_ms: int, fake_emb):
    """Insert a cr_contexts user_prompt row with embedding."""
    def _mk(session_id: int, content: str, *, iteration: int = 1,
            created_at: int | None = None) -> int:
        cur = conn.execute(
            "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
            "VALUES (?, 'user_prompt', ?, ?, ?, ?)",
            (session_id, content, iteration,
             vec_to_blob(fake_emb(content)), created_at or now_ms),
        )
        return int(cur.lastrowid)
    return _mk
