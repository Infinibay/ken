"""Re-encoding embeddings + model-drift probe validation."""

from __future__ import annotations

import time

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.embedder import vec_to_blob
from ken.reembed import (
    PROBE_TEXT,
    embedding_mismatch,
    reembed,
    stored_embedding_info,
    validate_embeddings,
)


class FakeEmbedder:
    """Deterministic embedder whose vectors depend on a seed and dim."""

    def __init__(self, name: str, dim: int = 4, shift: float = 0.0) -> None:
        self.model_name = name
        self._dim = dim
        self._shift = shift

    @property
    def dim(self) -> int:
        return self._dim

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        out = []
        for t in texts:
            base = np.array(
                [(hash((t, i)) % 1000) / 1000.0 + self._shift for i in range(self._dim)],
                dtype=np.float32,
            )
            out.append(base)
        return out

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed_passages(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "ken.db"
    conn = connect(path)
    init_schema(conn)
    now_ms = int(time.time() * 1000)
    zero = vec_to_blob(np.zeros(4, dtype=np.float32))
    conn.execute(
        "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
        "VALUES ('src/a.py','python',?,?,?,?)",
        (b"\x00" * 32, now_ms, now_ms, zero),
    )
    conn.execute(
        "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, "
        "docstring, embedding) VALUES (1,'function','go','go',1,2,'does things',?)",
        (zero,),
    )
    conn.execute(
        "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('a', ?)", (now_ms,)
    )
    conn.execute(
        "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
        "VALUES (1,'user_prompt','fix the thing',0,?,?)",
        (zero, now_ms),
    )
    yield conn
    conn.close()


def test_reembed_reencodes_every_table(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    result = reembed(db)
    assert result["files"] == 1
    assert result["symbols"] == 1
    assert result["prompts"] == 1
    assert result["dim"] == 4
    # vectors are no longer the zero placeholders — and they now live in the
    # mapped store, with the row holding only a pointer to them
    row = db.execute("SELECT embedding, vec_slot FROM ci_files").fetchone()
    assert row["embedding"] is None
    assert row["vec_slot"] is not None
    from ken.vectors import VectorStore, project_root_for

    store = VectorStore(project_root_for(db), "ci_files", dim=4)
    assert np.any(store.read([int(row["vec_slot"])])[0] != 0)


def test_reembed_records_model_and_dim(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    assert stored_embedding_info(db) == ("model-a", 4)


def test_probe_validates_same_model(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    report = validate_embeddings(db)
    assert report["ok"] is True
    assert report["probe_cosine"] == pytest.approx(1.0, abs=1e-4)


def test_probe_detects_drift_at_same_dimension(db, monkeypatch):
    """The whole point: a different model with the SAME dim must be caught."""
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    # Same name and dim, but a shifted vector space (e.g. pooling change).
    monkeypatch.setattr(
        "ken.reembed.get_embedder", lambda: FakeEmbedder("model-a", dim=4, shift=5.0)
    )
    report = validate_embeddings(db)
    assert report["ok"] is False
    assert "probe cosine" in report["reason"]


def test_probe_detects_dimension_change(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("big", dim=8))
    report = validate_embeddings(db)
    assert report["ok"] is False
    assert "dimension changed" in report["reason"]


def test_probe_missing_before_first_reembed(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    report = validate_embeddings(db)
    assert report["ok"] is False
    assert "no probe stored" in report["reason"]


def test_embedding_mismatch_by_name(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    assert embedding_mismatch(db, "model-a") is None
    msg = embedding_mismatch(db, "model-b")
    assert msg and "model-a" in msg and "model-b" in msg


def test_probe_text_is_stored(db, monkeypatch):
    monkeypatch.setattr("ken.reembed.get_embedder", lambda: FakeEmbedder("model-a"))
    reembed(db)
    row = db.execute("SELECT value FROM meta WHERE key='embed_probe_text'").fetchone()
    assert row["value"] == PROBE_TEXT
