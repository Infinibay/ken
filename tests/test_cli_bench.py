"""Ranker benchmark CLI over JSONL prompt fixtures."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ken import _paths
from ken.cli import main
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
            conn.execute(
                "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
                "VALUES (?, 'python', ?, ?, ?, ?)",
                (path, b"\x00" * 32, now_ns, now_ms, vec_to_blob(emb)),
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
    assert "1. hit:" in out


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
