"""CLI access to rank/explain daemon endpoints."""

from __future__ import annotations

from pathlib import Path

from ken.cli import main


def test_rank_cli_prints_context_block(monkeypatch, capsys, tmp_path):
    calls = []

    def fake_post(project_root: Path, path: str, payload: dict):
        calls.append((project_root, path, payload))
        return {"ok": True, "context_block": "<context-rank>\nsrc/a.py\n</context-rank>"}

    monkeypatch.setattr("ken.daemon.client.post", fake_post)

    rc = main(["rank", "--path", str(tmp_path), "--verbose", "2", "inspect", "parser"])

    assert rc == 0
    assert calls == [
        (
            tmp_path.resolve(),
            "/rank",
            {"query": "inspect parser", "verbose": 2},
        )
    ]
    assert "src/a.py" in capsys.readouterr().out


def test_rank_cli_stats_prints_size_summary(monkeypatch, capsys, tmp_path):
    def fake_post(project_root: Path, path: str, payload: dict):
        assert project_root == tmp_path.resolve()
        assert path == "/rank"
        assert payload == {"query": "inspect parser", "verbose": 1}
        return {
            "ok": True,
            "context_block": "<context-rank>\nsrc/a.py\n</context-rank>",
            "context_chars": 39,
            "context_est_tokens": 10,
            "files": 1,
            "symbols": 0,
            "findings": 0,
        }

    monkeypatch.setattr("ken.daemon.client.post", fake_post)

    rc = main(["rank", "--path", str(tmp_path), "--stats", "inspect", "parser"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "src/a.py" in captured.out
    assert "context: 39 chars, ~10 tokens; files=1, symbols=0, findings=0" in captured.err


def test_rank_cli_stats_falls_back_to_context_block_size(monkeypatch, capsys, tmp_path):
    block = "<context-rank>\nsrc/a.py\n</context-rank>"
    monkeypatch.setattr(
        "ken.daemon.client.post",
        lambda *_args, **_kwargs: {
            "ok": True,
            "context_block": block,
            "files": 1,
            "symbols": 0,
            "findings": 0,
        },
    )

    rc = main(["rank", "--path", str(tmp_path), "--stats", "inspect"])

    captured = capsys.readouterr()
    assert rc == 0
    assert block in captured.out
    assert f"context: {len(block)} chars, ~{(len(block) + 3) // 4} tokens" in captured.err


def test_rank_cli_passes_max_chars(monkeypatch, tmp_path):
    calls = []

    def fake_post(project_root: Path, path: str, payload: dict):
        calls.append((project_root, path, payload))
        return {"ok": True, "context_block": ""}

    monkeypatch.setattr("ken.daemon.client.post", fake_post)

    rc = main(["rank", "--path", str(tmp_path), "--max-chars", "1200", "inspect"])

    assert rc == 0
    assert calls == [
        (
            tmp_path.resolve(),
            "/rank",
            {"query": "inspect", "verbose": 1, "max_chars": 1200},
        )
    ]


def test_rank_cli_reports_daemon_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "ken.daemon.client.post",
        lambda *_args, **_kwargs: {"ok": False, "error": "no cached prompt"},
    )

    rc = main(["rank", "--path", str(tmp_path)])

    assert rc == 1
    assert "no cached prompt" in capsys.readouterr().err


def test_explain_cli_prints_json(monkeypatch, capsys, tmp_path):
    def fake_post(project_root: Path, path: str, payload: dict):
        assert project_root == tmp_path.resolve()
        assert path == "/explain"
        assert payload == {"query": "why cli.py"}
        return {"ok": True, "prompt": "why cli.py", "channels": {}}

    monkeypatch.setattr("ken.daemon.client.post", fake_post)

    rc = main(["explain", "--path", str(tmp_path), "why", "cli.py"])

    assert rc == 0
    out = capsys.readouterr().out
    assert '"prompt": "why cli.py"' in out
    assert '"channels": {}' in out


def test_explain_cli_json_returns_failure_for_error(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "ken.daemon.client.post",
        lambda *_args, **_kwargs: {"ok": False, "error": "ranker failed"},
    )

    rc = main(["explain", "--path", str(tmp_path), "--json"])

    assert rc == 1
    assert '"ok": false' in capsys.readouterr().out
