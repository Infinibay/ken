from pathlib import Path

import numpy as np

from ken.db import connect, init_schema
from ken.indexer import index_files


class Encoder:
    def embed_passages(self, texts):
        return [np.array([1.0, 0.0] if "cookie" in text.lower() else [0.0, 1.0],
                         dtype=np.float32) for text in texts]

    def embed_query(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


def indexed(tmp_path):
    source = tmp_path / "client.py"
    source.write_text("def unrelated():\n    return 0\n"
                      "def persist_state(jar):\n    jar.store('cookie')\n"
                      "def fail():\n    raise ValueError('CONFLICT_SENTINEL')\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("client.py")])
    return conn


def profile():
    from ken.retrieval.profile import EncoderSpec, RetrievalProfile
    spec = EncoderSpec("test/encoder", "a" * 40, "provided")
    return RetrievalProfile(spec, spec)


def test_union_recovers_answer_absent_from_other_channel(tmp_path):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.representations import index_embeddings
    with indexed(tmp_path) as conn:
        encoders = {"identity": Encoder(), "behavior": Encoder()}
        index_embeddings(conn, profile(), encoders=encoders)
        semantic = retrieve(conn, tmp_path, SearchRequest("browser state"),
                            profile(), encoders=encoders)
        assert semantic[0].entity.qualname == "persist_state"
        lexical = retrieve(conn, tmp_path, SearchRequest("CONFLICT_SENTINEL"),
                           profile(), encoders=encoders)
        assert "fail" in {c.entity.qualname for c in lexical}
        assert any(c.signals.get("bm25f", 0) > 0 for c in lexical)


def test_exact_lookup_survives_missing_dense_index(tmp_path):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    with indexed(tmp_path) as conn:
        candidates = retrieve(conn, tmp_path, SearchRequest("persist_state"))
        assert candidates[0].entity.qualname == "persist_state"
        assert candidates[0].signals["exact"] == 1


def test_exact_qualified_case_is_preserved_before_caseless_fallback(tmp_path):
    from ken.retrieval.candidates import retrieve, _exact
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.storage import load_passage_map
    (tmp_path / 'names.py').write_text(
        'class Box:\n    def read(self):\n        return 1\n'
        'class box:\n    def read(self):\n        return 2\n'
        'def OtherName():\n    return 3\n')
    class NoEncoder:
        def embed_query(self, text):
            raise AssertionError('unique literal lookup must not encode')
    with indexed(tmp_path) as conn:
        index_files(conn, tmp_path, [Path('names.py')])
        for query, expected in [('Box.read', 'Box.read'), ('box.read', 'box.read'),
                                ('OTHERNAME', 'OtherName')]:
            result = retrieve(conn, tmp_path, SearchRequest(query), profile(),
                encoders={'identity': NoEncoder(), 'behavior': NoEncoder()})
            assert [c.entity.qualname for c in result] == [expected]
        ambiguous = _exact(conn, load_passage_map(conn), SearchRequest('BOX.read'))
        assert {c.entity.qualname for c in ambiguous} == {'Box.read', 'box.read'}


def test_duplicate_passages_do_not_consume_entity_budget(tmp_path):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.representations import index_embeddings
    (tmp_path / "long.py").write_text("def huge():\n" + "    cookie = 1\n" * 1500 +
                                     "def small():\n    return 'cookie'\n")
    with indexed(tmp_path) as conn:
        index_files(conn, tmp_path, [Path("long.py")])
        encoders = {"identity": Encoder(), "behavior": Encoder()}
        index_embeddings(conn, profile(), encoders=encoders)
        candidates = retrieve(conn, tmp_path, SearchRequest("browser state"),
                              profile(), encoders=encoders)
        names = [c.entity.qualname for c in candidates]
        assert "huge" in names and "small" in names
        assert names.count("huge") == 1


def test_profile_rejects_mutable_revisions():
    from ken.retrieval.profile import EncoderSpec
    import pytest
    with pytest.raises(ValueError, match="revision"):
        EncoderSpec("model", "main", "sentence-transformers")


def test_dense_evidence_signals_survive_channel_merge(tmp_path):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.representations import index_embeddings
    with indexed(tmp_path) as conn:
        encoders = {"identity": Encoder(), "behavior": Encoder()}
        index_embeddings(conn, profile(), encoders=encoders)
        candidates = retrieve(conn, tmp_path, SearchRequest("browser state"),
                              profile(), encoders=encoders)
        target = next(c for c in candidates if c.entity.qualname == "persist_state")
        assert any("cosine_behavior" in p.signals and "cosine_identity" in p.signals
                   for p in target.passages)


def test_same_encoder_query_is_not_recomputed_for_each_view(tmp_path):
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.representations import index_embeddings
    class Counted(Encoder):
        calls = 0
        def embed_query(self, text):
            self.calls += 1
            return super().embed_query(text)
    encoder = Counted()
    encoders = {"identity": encoder, "behavior": encoder}
    with indexed(tmp_path) as conn:
        index_embeddings(conn, profile(), encoders=encoders)
        retrieve(conn, tmp_path, SearchRequest("browser state"), profile(), encoders=encoders)
    assert encoder.calls == 1


def test_unchanged_index_reuses_artifacts_without_encoding_or_changing_generation(tmp_path):
    from ken.retrieval.representations import index_embeddings
    from ken.retrieval.storage import generation
    class Counted(Encoder):
        encoded = 0
        def embed_passages(self, texts):
            self.encoded += len(texts)
            return super().embed_passages(texts)
    encoder = Counted()
    encoders = {"identity": encoder, "behavior": encoder}
    with indexed(tmp_path) as conn:
        index_embeddings(conn, profile(), encoders=encoders)
        encoded, before = encoder.encoded, generation(conn)
        index_embeddings(conn, profile(), encoders=encoders)
        assert encoder.encoded == encoded
        assert generation(conn) == before
