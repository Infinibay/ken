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
