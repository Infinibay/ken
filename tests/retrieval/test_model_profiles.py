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
