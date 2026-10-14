from pathlib import Path

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.indexer import index_files
from ken.retrieval.embedding_store import load_vectors, retrieval_snapshot
from ken.retrieval.indexing import index_project
from ken.retrieval.profile import EncoderSpec, RetrievalProfile
from ken.retrieval.storage import generation, load_passage_map


class Encoder:
    def __init__(self):
        self.texts = []
        self.fail = False

    def token_count(self, text):
        return len(text)

    def embed_passages(self, texts):
        if self.fail:
            raise RuntimeError("encoding unavailable")
        self.texts.extend(texts)
        return [np.array([1., 0.] if "cookie" in text else [0., 1.], dtype=np.float32)
                for text in texts]

    def embed_query(self, text):
        return np.array([1., 0.], dtype=np.float32)


def prepared(tmp_path, monkeypatch, *, tokenizer="code-lexical-v1"):
    from ken.retrieval import indexing
    (tmp_path / "client.py").write_text("def save(jar):\n    return jar\n")
    (tmp_path / "other.py").write_text("def stable():\n    return 'unrelated'\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    spec = EncoderSpec("provided", "a" * 40, "provided")
    profile = RetrievalProfile(spec, spec, max_tokens=128, passage_tokenizer=tokenizer)
    encoder = Encoder()
    encoders = {"identity": encoder, "behavior": encoder}
    index_project(conn, tmp_path, [Path("client.py"), Path("other.py")],
                  profile=profile, encoders=encoders)
    encoder.texts.clear()
    monkeypatch.setattr(indexing, "load_encoder", lambda spec: encoder)
    return conn, profile, encoder


def test_ordinary_file_edit_updates_both_views_without_encoding_unrelated_files(tmp_path, monkeypatch):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    conn, profile, encoder = prepared(tmp_path, monkeypatch)
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    stats = index_files(conn, tmp_path, [Path("client.py")])
    assert stats.parsed == 1
    passages = load_passage_map(conn)
    for view in ("identity", "behavior"):
        assert set(load_vectors(conn, view, profile.vector_revision(view)).ids) == set(passages)
    assert encoder.texts and all("other.py" not in text for text in encoder.texts)
    candidates = retrieve(conn, tmp_path, SearchRequest("browser state"), profile,
        encoders={"identity": encoder, "behavior": encoder})
    assert candidates[0].entity.qualname == "save"
    conn.close()


def test_encoder_failure_does_not_publish_new_file_or_passages(tmp_path, monkeypatch):
    conn, profile, encoder = prepared(tmp_path, monkeypatch)
    before = load_passage_map(conn)
    before_generation = generation(conn)
    encoder.fail = True
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    with pytest.raises(RuntimeError, match="encoding unavailable"):
        index_files(conn, tmp_path, [Path("client.py")])
    assert load_passage_map(conn) == before
    assert generation(conn) == before_generation
    for view in ("identity", "behavior"):
        assert set(load_vectors(conn, view, profile.vector_revision(view)).ids) == set(before)
    conn.close()


def test_incremental_edit_retains_actual_tokenizer_policy(tmp_path, monkeypatch):
    from ken.retrieval.indexing import source_policy_key
    conn, profile, encoder = prepared(tmp_path, monkeypatch, tokenizer="behavior-model")
    (tmp_path / "client.py").write_text("def save(jar):\n" + "    jar.store('cookie')\n" * 18)
    index_files(conn, tmp_path, [Path("client.py")])
    policies = conn.execute("SELECT extractor_version,tokenizer_version,max_tokens FROM ci_retrieval_files").fetchall()
    assert all(tuple(row) == source_policy_key(profile) for row in policies)
    assert all(encoder.token_count(p.fields["body"]) <= profile.max_tokens
               for p in load_passage_map(conn).values())
    conn.close()


def test_reader_keeps_complete_previous_views_during_atomic_file_edit(tmp_path, monkeypatch):
    conn, profile, _ = prepared(tmp_path, monkeypatch)
    reader = connect(tmp_path / "index.db")
    with retrieval_snapshot(reader):
        old = load_passage_map(reader)
        old_vectors = load_vectors(reader, "behavior", profile.vector_revision("behavior"))
        (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
        index_files(conn, tmp_path, [Path("client.py")])
        assert load_passage_map(reader) == old
        assert load_vectors(reader, "behavior", profile.vector_revision("behavior")).ids == old_vectors.ids
    current = load_passage_map(reader)
    assert current != old
    for view in ("identity", "behavior"):
        assert set(load_vectors(reader, view, profile.vector_revision(view)).ids) == set(current)
    reader.close()
    conn.close()


def test_unchanged_incremental_batch_does_not_load_encoder_or_scan_all_passages(tmp_path, monkeypatch):
    from ken.retrieval import indexing, storage
    conn, _, encoder = prepared(tmp_path, monkeypatch, tokenizer="behavior-model")
    def unexpected(*args, **kwargs):
        pytest.fail("unchanged file must not load models or scan corpus passages")
    monkeypatch.setattr(indexing, "load_encoder", unexpected)
    monkeypatch.setattr(storage, "load_passage_map", unexpected)
    stats = index_files(conn, tmp_path, [Path("client.py")])
    assert stats.unchanged == 1
    assert encoder.texts == []
    conn.close()


def test_source_changed_during_encoding_is_not_published(tmp_path, monkeypatch):
    from ken.retrieval.embedding_store import IndexVersionError
    conn, _, encoder = prepared(tmp_path, monkeypatch)
    before = load_passage_map(conn)
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    original = encoder.embed_passages
    def racing(texts):
        result = original(texts)
        (tmp_path / "client.py").write_text("def newer():\n    return 2\n")
        return result
    monkeypatch.setattr(encoder, "embed_passages", racing)
    with pytest.raises(IndexVersionError, match="source changed"):
        index_files(conn, tmp_path, [Path("client.py")])
    assert load_passage_map(conn) == before
    conn.close()


def test_profile_changed_during_encoding_rolls_back_source_and_vectors(tmp_path, monkeypatch):
    from ken.retrieval.embedding_store import IndexVersionError
    conn, _, encoder = prepared(tmp_path, monkeypatch)
    before = load_passage_map(conn)
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    original = encoder.embed_passages
    def racing(texts):
        result = original(texts)
        conn.execute("UPDATE meta SET value='concurrent-profile' WHERE key='retrieval_profile_fingerprint'")
        return result
    monkeypatch.setattr(encoder, "embed_passages", racing)
    with pytest.raises(IndexVersionError, match="profile changed"):
        index_files(conn, tmp_path, [Path("client.py")])
    assert load_passage_map(conn) == before
    conn.close()


def test_nonfinite_second_view_rolls_back_first_view_and_source(tmp_path, monkeypatch):
    conn, _, encoder = prepared(tmp_path, monkeypatch)
    before = load_passage_map(conn)
    artifacts = [tuple(row) for row in conn.execute("SELECT * FROM ci_passage_vectors ORDER BY passage_id,view")]
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    monkeypatch.setattr(encoder, "embed_passages", lambda texts: [np.array([np.nan, 1.])] * len(texts))
    with pytest.raises(ValueError, match="finite"):
        index_files(conn, tmp_path, [Path("client.py")])
    assert load_passage_map(conn) == before
    assert [tuple(row) for row in conn.execute("SELECT * FROM ci_passage_vectors ORDER BY passage_id,view")] == artifacts
    conn.close()


def test_edit_reclaims_only_retired_unreferenced_artifacts(tmp_path, monkeypatch):
    conn, _, _ = prepared(tmp_path, monkeypatch)
    (tmp_path / "client.py").write_text("def save(jar):\n    jar.store('cookie')\n")
    index_files(conn, tmp_path, [Path("client.py")])
    assert conn.execute("SELECT count(*) FROM ci_retrieval_embeddings e WHERE NOT EXISTS "
                        "(SELECT 1 FROM ci_passage_vectors v WHERE v.embedding_id=e.id)").fetchone()[0] == 0
    conn.close()
