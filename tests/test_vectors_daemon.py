"""The daemon's live-indexing path, against the vector store.

`ken serve` re-indexes edited files through `IndexQueue`, on its own connection,
while hooks read through another. That is the concurrency the store was designed
for, so it deserves a test that exercises the real queue rather than a stand-in:
edit a file, let the worker pick it up, and check the vector that comes back is
the new one, at the same slot, with the store still internally consistent.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from ken.daemon.index_queue import IndexQueue
from ken.db import connect, init_schema
from ken.vectors import VectorStore


class _Embedder:
    """Deterministic, and sensitive to content so an edit is visible."""

    model_name = "fake/daemon"

    @property
    def dim(self) -> int:
        return 8

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        out = []
        for t in texts:
            rng = np.random.default_rng(abs(hash(t)) & 0xFFFF_FFFF)
            v = rng.normal(size=8).astype(np.float32)
            out.append(v / np.linalg.norm(v))
        return out

    def embed_queries(self, texts: list[str]) -> list[np.ndarray]:
        return self.embed_passages(texts)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".ken").mkdir()
    conn = connect(tmp_path / ".ken" / "ken.db")
    init_schema(conn)
    conn.close()
    return tmp_path


def _drain(q: IndexQueue, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if q._queue.empty():
            time.sleep(0.15)  # let the in-flight batch land
            if q._queue.empty():
                return
        time.sleep(0.05)
    raise AssertionError("index queue did not drain")


def test_daemon_reindex_writes_through_the_vector_store(project):
    src = project / "mod.py"
    src.write_text("def alpha():\n    return 1\n", encoding="utf-8")

    q = IndexQueue(project, embedder=_Embedder())
    q.start()
    try:
        q.reindex("mod.py")
        _drain(q)
    finally:
        q.stop()

    conn = connect(project / ".ken" / "ken.db")
    row = conn.execute("SELECT vec_slot, embedding FROM ci_files").fetchone()
    assert row["vec_slot"] is not None
    assert row["embedding"] is None, "the daemon must not fall back to inline blobs"
    store = VectorStore(project, "ci_files", dim=8)
    assert np.linalg.norm(store.read([int(row["vec_slot"])])[0]) == pytest.approx(1.0, abs=1e-6)
    assert store.verify(conn)["leaked"] == 0
    conn.close()


def test_editing_a_file_updates_its_vector_in_place(project):
    """A re-indexed file must reuse its own slot. If it did not, an actively
    edited repo would grow the store without bound while the row count stayed
    flat — the daemon re-indexes on every save."""
    src = project / "mod.py"
    src.write_text("def alpha():\n    return 1\n", encoding="utf-8")

    q = IndexQueue(project, embedder=_Embedder())
    q.start()
    try:
        q.reindex("mod.py")
        _drain(q)
        conn = connect(project / ".ken" / "ken.db")
        slot_before = conn.execute("SELECT vec_slot FROM ci_files").fetchone()["vec_slot"]
        vec_before = VectorStore(project, "ci_files", dim=8).read([int(slot_before)])[0].copy()
        symbols_before = conn.execute(
            "SELECT COUNT(*) FROM ci_symbols WHERE vec_slot IS NOT NULL"
        ).fetchone()[0]
        conn.close()

        src.write_text("def beta():\n    return 2\n\ndef gamma():\n    return 3\n", encoding="utf-8")
        q.reindex("mod.py")
        _drain(q)
    finally:
        q.stop()

    conn = connect(project / ".ken" / "ken.db")
    slot_after = conn.execute("SELECT vec_slot FROM ci_files").fetchone()["vec_slot"]
    assert slot_after == slot_before, "the file row keeps its slot across a re-index"
    vec_after = VectorStore(project, "ci_files", dim=8).read([int(slot_after)])[0]
    assert not np.allclose(vec_before, vec_after), "the vector must reflect the new content"

    # The old symbol slots came back through the delete trigger and were taken
    # again, so two symbols do not cost four slots.
    from ken.vectors import high_water

    assert high_water(conn, "ci_symbols") <= max(2, symbols_before + 2)
    store = VectorStore(project, "ci_symbols", dim=8)
    assert store.verify(conn)["double_booked"] == 0
    conn.close()


def test_deleting_a_file_through_the_daemon_frees_every_slot(project):
    src = project / "mod.py"
    src.write_text("def alpha():\n    '''Doc.'''\n    return 1\n", encoding="utf-8")

    q = IndexQueue(project, embedder=_Embedder())
    q.start()
    try:
        q.reindex("mod.py")
        _drain(q)
        src.unlink()
        q.delete("mod.py")
        _drain(q)
    finally:
        q.stop()

    conn = connect(project / ".ken" / "ken.db")
    assert conn.execute("SELECT COUNT(*) FROM ci_files").fetchone()[0] == 0
    for space in ("ci_files", "ci_symbols", "ci_intent_sources"):
        store = VectorStore(project, space, dim=8)
        report = store.verify(conn)
        assert report["referenced"] == 0
        assert report["leaked"] == 0, f"{space} leaked {report['leaked']} slots"
    conn.close()


def test_a_reader_on_another_connection_sees_daemon_writes(project):
    """Hooks read through a different connection than the indexer writes on."""
    from ken.vectors import live_scores

    src = project / "mod.py"
    src.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    reader = connect(project / ".ken" / "ken.db")

    q = IndexQueue(project, embedder=_Embedder())
    q.start()
    try:
        q.reindex("mod.py")
        _drain(q)
    finally:
        q.stop()

    target = _Embedder().embed_passages(["text python mod"])[0]
    hit = live_scores(reader, "ci_files", target)
    assert hit is not None, "the reader must find the store the writer created"
    slots, sims = hit
    assert slots.size >= 1
    assert sims.size == slots.size
    reader.close()
