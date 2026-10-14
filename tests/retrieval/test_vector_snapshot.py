from pathlib import Path

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.indexer import index_files
from ken.vectors import immediate

REV = "model@" + "a" * 40


def project(tmp_path):
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    (tmp_path / "x.py").write_text("def before():\n    return 'old'\n")
    index_files(conn, tmp_path, [Path("x.py")])
    return conn


def put(conn):
    from ken.retrieval.embedding_store import put_embeddings
    ids = [r[0] for r in conn.execute("SELECT id FROM ci_passages")]
    with immediate(conn):
        put_embeddings(conn, "behavior", REV,
                       {i: "same identity" for i in ids},
                       {i: np.array([0.6, 0.8], dtype=np.float32) for i in ids})
    return ids


def test_slot_reuse_cannot_pair_old_score_with_new_owner(tmp_path):
    from ken.retrieval.embedding_store import load_vectors, retrieval_snapshot
    from ken.retrieval.storage import load_passage_map
    writer = project(tmp_path)
    old_ids = put(writer)
    reader = connect(tmp_path / "index.db")
    with retrieval_snapshot(reader):
        old = load_vectors(reader, "behavior", REV)
        (tmp_path / "x.py").write_text("def after():\n    return 'new'\n")
        index_files(writer, tmp_path, [Path("x.py")])
        new_ids = put(writer)
        assert new_ids != old_ids
        resolved = load_passage_map(reader, old.ids)
        assert {p.entity.qualname for p in resolved.values()} == {"before"}
        assert load_vectors(reader, "behavior", REV).ids == old.ids
    assert {p.entity.qualname for p in load_passage_map(reader).values()} == {"after"}
    assert load_vectors(reader, "behavior", REV).ids != old.ids
    reader.close()
    writer.close()


def test_compaction_keeps_active_reader_generation_alive(tmp_path):
    from ken.retrieval.embedding_store import load_vectors, retrieval_snapshot, reclaim_embeddings
    writer = project(tmp_path)
    put(writer)
    reader = connect(tmp_path / "index.db")
    with retrieval_snapshot(reader):
        old = load_vectors(reader, "behavior", REV)
        with immediate(writer):
            writer.execute("DELETE FROM ci_files")
            assert reclaim_embeddings(writer) > 0
        assert load_vectors(reader, "behavior", REV).ids == old.ids
        assert np.array_equal(load_vectors(reader, "behavior", REV).matrix, old.matrix)
    assert load_vectors(reader, "behavior", REV).ids == ()
    reader.close()
    writer.close()


def test_rollback_never_publishes_unwritten_vectors(tmp_path):
    from ken.retrieval.embedding_store import put_embeddings, load_vectors
    with project(tmp_path) as conn:
        pid = conn.execute("SELECT id FROM ci_passages").fetchone()[0]
        with pytest.raises(RuntimeError):
            with immediate(conn):
                put_embeddings(conn, "behavior", REV, {pid: "old"},
                               {pid: np.array([1.0, 0.0], dtype=np.float32)})
                raise RuntimeError("write failed")
        assert load_vectors(conn, "behavior", REV).ids == ()


def test_model_revision_mismatch_and_nonfinite_vectors_are_rejected(tmp_path):
    from ken.retrieval.embedding_store import put_embeddings, load_vectors, IndexVersionError
    with project(tmp_path) as conn:
        ids = put(conn)
        with pytest.raises(IndexVersionError, match="reindex"):
            load_vectors(conn, "behavior", "model@" + "b" * 40)
        with immediate(conn):
            with pytest.raises(ValueError, match="finite"):
                put_embeddings(conn, "behavior", REV, {ids[0]: "bad"},
                               {ids[0]: np.array([float("nan"), 0.0], dtype=np.float32)})


def test_vectors_are_immutable_and_text_artifacts_are_deduplicated(tmp_path):
    from ken.retrieval.embedding_store import load_vectors
    with project(tmp_path) as conn:
        put(conn)
        view = load_vectors(conn, "behavior", REV)
        assert conn.execute("SELECT COUNT(*) FROM ci_retrieval_embeddings").fetchone()[0] == 1
        with pytest.raises(ValueError):
            view.matrix[0, 0] = 99
