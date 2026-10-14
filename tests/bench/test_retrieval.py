"""Acceptance tests for the strict, source-grounded retrieval evaluator."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest


SOURCE = "def clear_auth(headers):\n    if redirected:\n        headers.pop('Authorization', None)\n"
HASH = hashlib.sha256(SOURCE.encode()).hexdigest()
ENTITY = {"kind": "function", "qualname": "clear_auth", "owner": None, "definition_ordinal": 0}


def case(i=0):
    return {
        "id": str(i), "repo_id": f"repo{i // 25}", "repo_commit": "a" * 40,
        "query": "¿Dónde se retira la autorización tras una redirección?",
        "language": "en" if i % 25 < 15 else "es",
        "purpose": "implementation" if i < 210 else ("identity" if i < 255 else "usage"),
        "behavior_group": f"behavior-{i}", "answerable": True,
        "alternatives": [{"path": "auth.py", "source_hash": HASH, "entity": ENTITY,
                          "anchors": [{"start_line": 3, "end_line": 3}]}],
    }


def answer(i=0):
    return {"id": str(i), "results": [{
        "path": "auth.py", "entity": ENTITY, "source_hash": HASH,
        "evidence": [{"start_line": 2, "end_line": 3,
                      "content": "    if redirected:\n        headers.pop('Authorization', None)"}],
    }]}


def evaluate(tmp_path, cases, answers):
    from ken.bench.retrieval import evaluate
    (tmp_path / "auth.py").write_text(SOURCE)
    roots = {c["repo_id"]: tmp_path for c in cases}
    return evaluate(cases, answers, roots=roots)


def test_gate_rejects_269_of_300_and_accepts_270(tmp_path):
    from ken.bench.retrieval import check_gate
    cases = [case(i) for i in range(300)]
    # One miss at a time per repository and locale; keep each required slice >=90%.
    misses = {i for i in range(300) if i % 25 in (0, 15)}
    misses |= {26, 51, 76, 101, 226, 276}
    good = [answer(i) if i not in misses else {"id": str(i), "results": []} for i in range(300)]
    report = evaluate(tmp_path, cases, good)
    assert report["strict_top1"]["hits"] == 270
    assert not check_gate(report)
    good[201] = {"id": "201", "results": []}
    report = evaluate(tmp_path, cases, good)
    assert report["strict_top1"]["hits"] == 269
    assert any("strict_top1" in failure for failure in check_gate(report))


@pytest.mark.parametrize("mutation", ["file_only", "owner", "docstring", "stale", "invented_content"])
def test_file_only_wrong_owner_or_unfaithful_evidence_is_a_miss(tmp_path, mutation):
    hit = answer()
    result = hit["results"][0]
    if mutation == "file_only":
        result["entity"] = None
    elif mutation == "owner":
        result["entity"] = {**ENTITY, "qualname": "Wrong.clear_auth", "owner": "Wrong"}
    elif mutation == "docstring":
        result["evidence"] = [{"start_line": 1, "end_line": 1, "content": "def clear_auth(headers):"}]
    elif mutation == "stale":
        result["source_hash"] = "0" * 64
    else:
        result["evidence"][0]["content"] = "invented code"
    assert evaluate(tmp_path, [case()], [hit])["strict_top1"]["hits"] == 0


def test_errors_abstentions_and_missing_rows_remain_in_denominator(tmp_path):
    report = evaluate(tmp_path, [case(i) for i in range(4)],
                      [answer(0), {"id": "1", "error": "failed"}, {"id": "2", "results": []}])
    assert report["strict_top1"] == {"hits": 1, "total": 4, "rate": 0.25}
    assert report["missing_response_ids"] == ["3"]


def test_duplicate_and_unknown_response_ids_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(tmp_path, [case()], [answer(), answer()])
    with pytest.raises(ValueError, match="unknown"):
        evaluate(tmp_path, [case()], [answer(9)])


def test_global_90_cannot_hide_spanish_failure(tmp_path):
    from ken.bench.retrieval import check_gate
    cases = [case(i) for i in range(300)]
    responses = [answer(i) for i in range(300)]
    for i in [i for i in range(300) if i % 25 >= 15][:20]:
        responses[i]["results"] = []
    report = evaluate(tmp_path, cases, responses)
    assert report["strict_top1"]["rate"] > 0.90
    assert any("language:es" in failure for failure in check_gate(report))


def test_alternative_anchors_must_be_satisfied_together(tmp_path):
    c = case()
    c["alternatives"][0]["anchors"].append({"start_line": 1, "end_line": 1})
    assert evaluate(tmp_path, [c], [answer()])["strict_top1"]["hits"] == 0
    c["alternatives"].append(copy.deepcopy(case()["alternatives"][0]))
    assert evaluate(tmp_path, [c], [answer()])["strict_top1"]["hits"] == 1


def test_dataset_rejects_invalid_paths_spans_and_hashes(tmp_path):
    from ken.bench.dataset import load_dataset
    p = tmp_path / "cases.jsonl"
    for key, value in [("path", "../auth.py"), ("source_hash", "bad"), ("anchors", [])]:
        c = case()
        c["alternatives"][0][key] = value
        p.write_text(json.dumps(c) + "\n")
        with pytest.raises(ValueError):
            load_dataset(p)


def test_gold_metadata_never_enters_search_request():
    from ken.bench.retrieval import request_for_case
    request = request_for_case(case())
    assert request == {"query": case()["query"], "purpose": "auto", "target": "symbol",
                       "limit": 10, "max_chars": 12000}
    assert "alternatives" not in request and "answerable" not in request


def test_scorer_does_not_charge_case_identifier_as_engine_output(tmp_path):
    c = case()
    c["id"] = "x" * 13000
    a = answer()
    a["id"] = c["id"]
    assert evaluate(tmp_path, [c], [a])["strict_top1"]["hits"] == 1


def test_evidence_outside_source_or_budget_is_invalid(tmp_path):
    hit = answer()
    hit["results"][0]["evidence"][0]["end_line"] = 900
    assert evaluate(tmp_path, [case()], [hit])["strict_top1"]["hits"] == 0
    hit = answer()
    hit["explain"] = "x" * 12001
    assert evaluate(tmp_path, [case()], [hit])["strict_top1"]["hits"] == 0


def test_warnings_are_not_fatal_and_lower_gate_is_rejected(tmp_path):
    from ken.bench.retrieval import check_gate
    hit = answer()
    hit["warnings"] = ["some optional context was unavailable"]
    report = evaluate(tmp_path, [case()], [hit])
    assert report["strict_top1"]["hits"] == 1
    for floor in (0.89, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            check_gate(report, {"min_top1": floor})


def test_cli_retrieval_scores_records_without_changing_legacy_bench(tmp_path, capsys):
    from ken.cli import main
    (tmp_path / "auth.py").write_text(SOURCE)
    data, responses, roots, policy = [tmp_path / name for name in
                                    ("cases.jsonl", "responses.jsonl", "roots.json", "policy.json")]
    data.write_text(json.dumps(case()) + "\n")
    responses.write_text(json.dumps(answer()) + "\n")
    roots.write_text(json.dumps({"repo0": str(tmp_path)}))
    policy.write_text(json.dumps({"min_top1": 0.90}))
    assert main(["bench", str(data), "--engine", "retrieval", "--responses", str(responses),
                 "--roots", str(roots), "--gate", str(policy), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["strict_top1"]["hits"] == 1
    assert any("language:es" in f for f in report["failures"])
