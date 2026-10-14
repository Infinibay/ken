def test_runner_passes_only_public_inputs_and_preserves_failures():
    from ken.bench.runner import run_cases
    seen = []
    def execute(repo_id, request):
        seen.append((repo_id, request))
        if request["query"] == "fail":
            raise ValueError("cannot search")
        return {"results": []}
    cases = [{"id": "a", "repo_id": "r", "query": "search", "alternatives": ["secret"]},
             {"id": "b", "repo_id": "r", "query": "fail", "answerable": False}]
    responses = run_cases(cases, execute)
    assert len(responses) == 2
    assert responses[1]["id"] == "b" and "error" in responses[1]
    assert all(set(request) == {"query", "target", "purpose", "limit", "max_chars"}
               for _, request in seen)
    assert all(request["purpose"] == "auto" for _, request in seen)


def test_live_runner_builds_real_index_and_reports_all_cases(tmp_path):
    from ken.bench.runner import run_live
    root = tmp_path / "project"
    root.mkdir()
    (root / "auth.py").write_text("def clear_auth():\n    return 'Authorization'\n")
    cases = [{"id": "a", "repo_id": "r", "query": "clear_auth"}]
    result = run_live(cases, {"r": root}, tmp_path / "indexes")
    assert len(result["responses"]) == 1
    first = result["responses"][0]["results"][0]
    assert first["entity"]["qualname"] == "clear_auth"
    assert "return 'Authorization'" in first["evidence"][0]["content"]
    assert result["index_stats"]["r"]["passages"] > 0
    assert result["timings_ms"]


def test_live_control_encoder_is_shared_by_indexing_and_public_query_only(tmp_path):
    import numpy as np
    from ken.bench.runner import run_live
    from ken.retrieval.profile import EncoderSpec, RetrievalProfile
    (tmp_path / "auth.py").write_text("def clear_auth():\n    erase_credentials()\n")
    class Encoder:
        queries = []
        def embed_passages(self, texts):
            return [np.array([1., 0.], dtype=np.float32) for _ in texts]
        def embed_query(self, query):
            self.queries.append(query)
            return np.array([1., 0.], dtype=np.float32)
    encoder = Encoder()
    spec = EncoderSpec("control/provided", "a" * 40, "provided")
    cases = [{"id": "a", "repo_id": "r", "query": "erase credentials",
              "purpose": "tests", "alternatives": ["unavailable to producer"]}]
    result = run_live(cases, {"r": tmp_path}, tmp_path / "indexes",
        profile=RetrievalProfile(spec, spec), encoders={"identity": encoder, "behavior": encoder})
    assert result["responses"][0]["results"][0]["entity"]["qualname"] == "clear_auth"
    assert encoder.queries == ["erase credentials"]
