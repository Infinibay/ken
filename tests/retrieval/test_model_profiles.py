import sys
from types import SimpleNamespace


def test_backend_pins_revision_disables_remote_code_and_exposes_token_count(monkeypatch):
    from ken.embedder.st_backend import SentenceTransformerEmbedder
    calls = []
    def factory(name, **kwargs):
        calls.append((name, kwargs))
        return SimpleNamespace(max_seq_length=1024, get_embedding_dimension=lambda: 3,
            tokenizer=SimpleNamespace(encode=lambda text, **kwargs: [1, 2, 3]))
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=factory))
    encoder = SentenceTransformerEmbedder("model", device="cpu", revision="a" * 40,
                                         local_files_only=True, trust_remote_code=False)
    assert encoder.token_count("some text") == 3
    assert calls[0][1]["revision"] == "a" * 40
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["trust_remote_code"] is False


def test_bundled_static_profile_revision_matches_actual_artifact():
    from ken.retrieval.profile import default_profile, load_encoder
    profile = default_profile()
    encoder = load_encoder(profile.behavior)
    assert encoder.token_count("clearAuth headers") > 0
    assert len(encoder.embed_query("clearAuth")) == encoder.dim


def test_local_profile_resolves_snapshot_before_model_library_can_probe_network(monkeypatch):
    from ken.retrieval.profile import EncoderSpec, load_encoder
    calls = []
    def snapshot(model, **kwargs):
        calls.append((model, kwargs))
        return "/tmp/immutable-model-snapshot"
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=snapshot))
    spec = EncoderSpec("test/local-model", "d" * 40, "sentence-transformers",
                       dtype="float16", sequence_length=384, batch_size=8)
    encoder = load_encoder(spec)
    assert calls == [(spec.model_id, {"revision": spec.revision, "local_files_only": True, "token": False})]
    assert encoder.model_path == "/tmp/immutable-model-snapshot"
    assert encoder.dtype == "float16"
    assert encoder.sequence_length == 384
    assert encoder.batch_size == 8


def test_encoder_math_and_truncation_are_part_of_profile_identity():
    from ken.retrieval.profile import EncoderSpec
    a = EncoderSpec("model", "f" * 40, "sentence-transformers")
    b = EncoderSpec("model", "f" * 40, "sentence-transformers", dtype="float16")
    c = EncoderSpec("model", "f" * 40, "sentence-transformers", sequence_length=384)
    assert len({a.key, b.key, c.key}) == 3


def test_mlx_backend_is_an_explicit_distinct_profile():
    from ken.retrieval.profile import EncoderSpec
    torch = EncoderSpec("Qwen/Qwen3-Embedding-0.6B", "a" * 40, "sentence-transformers")
    mlx = EncoderSpec("Qwen/Qwen3-Embedding-0.6B", "a" * 40, "mlx")
    assert torch.key != mlx.key


def test_projection_preserves_body_before_trimming_metadata_to_actual_model_budget():
    from ken.retrieval.model import EntityKey, Passage, Span
    from ken.retrieval.profile import EncoderSpec, RetrievalProfile
    from ken.retrieval.representations import bounded_passage_text
    spec = EncoderSpec("provided", "b" * 40, "provided", sequence_length=64)
    profile = RetrievalProfile(spec, spec, max_tokens=16)
    passage = Passage(EntityKey("a.py", "function", "f"), Span(1, 1),
        {"identity": "f", "path": "a.py", "signature": "signature " * 100,
         "documentation": "docs " * 100, "body": "raise ERROR"}, "a" * 64, Span(1, 1))
    class Tokenizer:
        def token_count(self, text):
            return len(text)
    text = bounded_passage_text(passage, "behavior", profile, Tokenizer())
    assert "raise ERROR" in text
    assert len(text) <= 58


def test_profile_source_policy_can_use_actual_behavior_tokenizer():
    from ken.retrieval.indexing import passage_policy
    from ken.retrieval.profile import EncoderSpec, RetrievalProfile
    spec = EncoderSpec("provided", "e" * 40, "provided")
    profile = RetrievalProfile(spec, spec, max_tokens=128, passage_tokenizer="behavior-model")
    class Tokenizer:
        def token_count(self, text):
            return len(text) * 2
    policy = passage_policy(profile, encoder=Tokenizer())
    assert policy.count_tokens("foo") == 6
    assert policy.max_tokens == 128
    assert spec.revision in policy.tokenizer_version


def test_ordering_and_evidence_policy_roundtrip_and_change_profile_identity():
    from ken.retrieval.profile import EncoderSpec, JointRanking, RetrievalProfile
    spec = EncoderSpec("provided", "e" * 40, "provided")
    baseline = RetrievalProfile(spec, spec)
    ranked = RetrievalProfile(spec, spec, joint=JointRanking(spec, candidate_limit=80, max_windows=4))
    assert ranked.fingerprint != baseline.fingerprint
    assert RetrievalProfile.from_dict(ranked.to_dict()) == ranked


def test_public_search_uses_configured_joint_ranking_and_evidence(tmp_path):
    from pathlib import Path
    import numpy as np
    from ken.db import connect, init_schema
    from ken.retrieval.indexing import index_project
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.profile import EncoderSpec, JointRanking, RetrievalProfile
    from ken.retrieval.service import search
    (tmp_path / "a.py").write_text("def left():\n    return 0\n\ndef right():\n    clear_secrets()\n")
    spec = EncoderSpec("provided", "e" * 40, "provided")
    profile = RetrievalProfile(spec, spec, joint=JointRanking(spec))
    class Encoder:
        def embed_passages(self, texts):
            return [np.array([1., 0.], dtype=np.float32) for _ in texts]
        def embed_query(self, text):
            return np.array([1., 0.], dtype=np.float32)
    class Judge:
        def score(self, query, documents, *, purpose):
            return [10. if "clear_secrets()" in doc else -2. for doc in documents]
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    encoders = {"identity": Encoder(), "behavior": Encoder()}
    index_project(conn, tmp_path, [Path("a.py")], profile=profile, encoders=encoders)
    response = search(conn, tmp_path, SearchRequest("erase credentials"), profile=profile,
                      encoders=encoders, judge=Judge()).to_dict()
    assert response["results"][0]["entity"]["qualname"] == "right"
    assert "clear_secrets()" in response["results"][0]["evidence"][0]["content"]
    assert response["profile_version"] == profile.fingerprint
    conn.close()
