"""Ranker benchmark CLI over JSONL prompt fixtures."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
import pytest

from ken import _paths
from ken.cli import _load_bench_cases, _ndcg_at_k, main
from ken.db import connect, init_schema
from ken.embedder import vec_to_blob


class FakeEmbedder:
    def embed_query(self, text: str) -> np.ndarray:
        if "parser" in text:
            return np.array([1.0, 0.0], dtype=np.float32)
        return np.array([0.0, 1.0], dtype=np.float32)


def _project(tmp_path: Path) -> Path:
    _paths.ken_dir(tmp_path).mkdir()
    _paths.meta_path(tmp_path).write_text("{}", encoding="utf-8")
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
        now_ms = int(time.time() * 1000)
        now_ns = int(time.time() * 1e9)
        for path, emb in [
            ("src/parser.py", np.array([1.0, 0.0], dtype=np.float32)),
            ("src/status.py", np.array([0.0, 1.0], dtype=np.float32)),
        ]:
            src = tmp_path / path
            src.parent.mkdir(parents=True, exist_ok=True)
            content = b"def indexed():\n    return 1\n"
            src.write_bytes(content)
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
                "VALUES (?, 'python', ?, ?, ?, ?)",
                (
                    path,
                    hashlib.blake2b(content, digest_size=32).digest(),
                    now_ns,
                    now_ms,
                    vec_to_blob(emb),
                ),
            )
    return tmp_path


def test_bench_cli_reports_recall(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "fix src/parser.py", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(["bench", "--path", str(root), str(dataset)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "cases=1" in out
    assert "case_recall=100.00%" in out
    assert "mrr=1.0000" in out
    assert "ndcg=1.0000" in out
    assert "avg_embed=" in out
    assert "avg_rank=" in out
    assert "avg_render=" in out
    assert "avg_e2e=" in out
    assert "1. hit:" in out
    assert "e2e=" in out.splitlines()[1]


@pytest.mark.parametrize("budget,expected_visible", [(0, ["a.py", "b.py", "c.py"]), (1, [])])
def test_bench_measures_exposure_after_caps_and_budget(
    monkeypatch, capsys, tmp_path, budget, expected_visible
):
    from ken.ranker import RankResult, RankedItem

    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(json.dumps({"prompt": "parser", "expected_files": ["src/parser.py"]}) + "\n")
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())
    result = RankResult(files=[RankedItem(p, "file", 5.0) for p in ["a.py", "b.py", "c.py", "src/parser.py"]])
    monkeypatch.setattr("ken.ranker.rank", lambda *args, **kwargs: result)
    assert main(["bench", "--path", str(root), "--max-chars", str(budget), "--json", str(dataset)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["expected_file_recall"] == 1.0
    assert data["mrr"] == 0.25
    assert data["visible_expected_file_recall"] == 0.0
    assert data["visible_case_recall"] == 0.0
    assert data["visible_mrr"] == 0.0
    assert data["results"][0]["visible_files"] == expected_visible


def test_bench_cli_preserves_empty_rankings_as_zero_metrics(
    monkeypatch, capsys, tmp_path
):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())
    monkeypatch.setattr(
        "ken.ranker.rank",
        lambda *args, **kwargs: type("Result", (), {"files": [], "empty": True})(),
    )

    rc = main(["bench", "--path", str(root), "--json", str(dataset)])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["case_recall"] == 0.0
    assert data["expected_file_recall"] == 0.0
    assert data["mrr"] == 0.0
    assert data["ndcg"] == 0.0
    assert data["results"][0]["ranked_files"] == []


def test_bench_cli_rejects_index_for_incompatible_project_root(capsys, tmp_path):
    (tmp_path / "indexed").mkdir()
    indexed_root = _project(tmp_path / "indexed")
    incompatible_root = tmp_path / "copy"
    incompatible_root.mkdir()
    shutil.copytree(indexed_root / ".ken", incompatible_root / ".ken")
    shared_path = incompatible_root / "src/parser.py"
    shared_path.parent.mkdir()
    shared_path.write_text("def unrelated():\n    return 2\n", encoding="utf-8")
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )

    rc = main(["bench", "--path", str(incompatible_root), str(dataset)])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "indexed files do not belong to the benchmark project root" in captured.err


def test_bench_cli_rejects_indexed_path_outside_project_root(capsys, tmp_path):
    root = _project(tmp_path)
    outside = tmp_path.parent / "outside-bench-source.py"
    outside.write_text("def indexed():\n    return 1\n", encoding="utf-8")
    with connect(_paths.db_path(root)) as conn:
        conn.execute(
            "UPDATE ci_files SET path = ? WHERE path = 'src/parser.py'",
            (str(outside),),
        )
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )

    rc = main(["bench", "--path", str(root), str(dataset)])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "indexed files do not belong to the benchmark project root" in captured.err


def test_bench_cli_rejects_same_paths_with_mismatched_content(capsys, tmp_path):
    (tmp_path / "indexed").mkdir()
    indexed_root = _project(tmp_path / "indexed")
    incompatible_root = tmp_path / "copy"
    shutil.copytree(indexed_root, incompatible_root)
    (incompatible_root / "src/parser.py").write_text(
        "def unrelated():\n    return 2\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )

    rc = main(["bench", "--path", str(incompatible_root), str(dataset)])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "indexed files do not belong to the benchmark project root" in captured.err


@pytest.mark.parametrize("top", ["0", "-1"])
def test_bench_cli_rejects_non_positive_top(capsys, tmp_path, top):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/parser.py"]})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["bench", "--path", str(root), "--top", top, str(dataset)])

    assert exc_info.value.code == 2
    assert "--top: must be a positive integer" in capsys.readouterr().err


def test_bench_cli_prints_json(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "status behavior", "expected_files": ["src/status.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(["bench", "--path", str(root), "--json", str(dataset)])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True
    assert data["case_recall"] == 1.0
    assert data["results"][0]["hits"] == ["src/status.py"]


def test_bench_cli_json_reports_ranking_quality_and_timings(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "prompt": "parser behavior",
                "expected_files": ["src/parser.py"],
                "judgments": {"src/parser.py": 3},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(["bench", "--path", str(root), "--json", str(dataset)])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    row = data["results"][0]
    assert data["mrr"] == row["reciprocal_rank"] == 1.0
    assert data["ndcg"] == row["ndcg"] == 1.0
    assert row["judgments"] == {"src/parser.py": 3.0}
    assert row["ranked_details"][0]["path"] == "src/parser.py"
    assert isinstance(row["ranked_details"][0]["score"], float)
    assert "reason" in row["ranked_details"][0]
    assert set(row["timings_ms"]) == {"embed", "rank", "render", "e2e"}
    assert all(elapsed >= 0.0 for elapsed in row["timings_ms"].values())
    assert row["timings_ms"]["e2e"] >= max(
        row["timings_ms"][phase] for phase in ("embed", "rank", "render")
    )
    assert set(data["avg_timings_ms"]) == {"embed", "rank", "render", "e2e"}
    assert data["avg_timings_ms"] == row["timings_ms"]


def test_bench_cli_averages_per_case_token_estimates(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        "\n".join(
            json.dumps({"prompt": prompt, "expected_files": [expected]})
            for prompt, expected in (
                ("parser behavior", "src/parser.py"),
                ("status behavior", "src/status.py"),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(["bench", "--path", str(root), "--json", str(dataset)])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    expected_average = round(
        sum(row["context_est_tokens"] for row in data["results"]) / len(data["results"]),
        1,
    )
    assert data["avg_context_est_tokens"] == expected_average


@pytest.mark.parametrize("row", [[], 42, "case", None], ids=["array", "number", "string", "null"])
def test_bench_cases_reject_non_object_rows(tmp_path, row):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(
        SystemExit,
        match=r"bench\.jsonl:1: benchmark case must be a JSON object",
    ):
        _load_bench_cases(dataset)


def test_bench_cases_reject_empty_expected_files(tmp_path):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": []}) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SystemExit,
        match=r"bench\.jsonl:1: expected_files must be a non-empty string list",
    ):
        _load_bench_cases(dataset)


def test_bench_cases_reject_duplicate_expected_files(tmp_path):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "prompt": "parser behavior",
                "expected_files": ["src/parser.py", "src/parser.py"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SystemExit,
        match=r"bench\.jsonl:1: expected_files must not contain duplicates",
    ):
        _load_bench_cases(dataset)


@pytest.mark.parametrize(
    ("expected_files", "judgments"),
    [
        (["src/parser.py", "src/status.py"], {"src/parser.py": 3}),
        (["src/parser.py"], {"src/parser.py": 3, "src/status.py": 1}),
        (["src/parser.py"], {"src/parser.py": 0}),
    ],
)
def test_bench_cases_require_positive_judgments_to_match_expected_files(
    tmp_path, expected_files, judgments
):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "prompt": "parser behavior",
                "expected_files": expected_files,
                "judgments": judgments,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SystemExit,
        match=r"bench\.jsonl:1: positive judgments must match expected_files",
    ):
        _load_bench_cases(dataset)


@pytest.mark.parametrize("grade", [float("nan"), float("inf"), float("-inf")])
def test_bench_cases_reject_non_finite_judgment_grades(tmp_path, grade):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "prompt": "parser behavior",
                "expected_files": ["src/parser.py"],
                "judgments": {"src/parser.py": grade},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SystemExit,
        match=r"bench\.jsonl:1: judgments must map file paths to grades 0\.\.3",
    ):
        _load_bench_cases(dataset)


def test_ndcg_at_k_uses_graded_relevance_and_rank_order():
    judgments = {"direct.py": 3.0, "support.py": 2.0}

    ideal = _ndcg_at_k(["direct.py", "support.py"], judgments, 2)
    reversed_order = _ndcg_at_k(["support.py", "direct.py"], judgments, 2)

    assert ideal == 1.0
    assert 0.0 < reversed_order < ideal


def test_ndcg_at_k_respects_cutoff_and_handles_no_relevance():
    judgments = {"direct.py": 3.0, "support.py": 2.0}

    assert _ndcg_at_k(["unrelated.py", "direct.py"], judgments, 1) == 0.0
    assert 0.0 < _ndcg_at_k(["unrelated.py", "direct.py"], judgments, 2) < 1.0
    assert _ndcg_at_k(["direct.py"], {}, 1) == 0.0


def test_bench_cli_explain_misses_includes_ranked_reasons(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/missing.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(["bench", "--path", str(root), "--json", "--explain-misses", str(dataset)])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    row = data["results"][0]
    assert row["misses"] == ["src/missing.py"]
    assert row["ranked_details"][0]["path"] == "src/parser.py"
    assert "reason" in row["ranked_details"][0]


def test_bench_cli_fails_under_case_recall_threshold(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/missing.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(
        [
            "bench",
            "--path",
            str(root),
            "--fail-under-case-recall",
            "0.9",
            str(dataset),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "case_recall=0.00%" in captured.out
    assert "FAIL: case_recall 0.0000 < 0.9000" in captured.err


def test_bench_cli_json_marks_threshold_failure(monkeypatch, capsys, tmp_path):
    root = _project(tmp_path)
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "parser behavior", "expected_files": ["src/missing.py"]})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("ken.embedder.get_embedder", lambda: FakeEmbedder())

    rc = main(
        [
            "bench",
            "--path",
            str(root),
            "--json",
            "--fail-under-expected-file-recall",
            "0.5",
            str(dataset),
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert data["ok"] is False
    assert data["failures"] == ["expected_file_recall 0.0000 < 0.5000"]


def test_bench_cli_reports_missing_project(capsys, tmp_path):
    dataset = tmp_path / "bench.jsonl"
    dataset.write_text(
        json.dumps({"prompt": "status", "expected_files": ["src/status.py"]}) + "\n",
        encoding="utf-8",
    )

    rc = main(["bench", "--path", str(tmp_path), str(dataset)])

    assert rc == 1
    assert "no .ken project" in capsys.readouterr().err
