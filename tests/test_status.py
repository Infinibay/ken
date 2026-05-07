"""Status report for index coverage and daemon health."""

from __future__ import annotations

import json
import time

import numpy as np

from ken import _paths
from ken.db import connect, init_schema
from ken.embedder import vec_to_blob
from ken.status import show_status, status_report


def _installed_project(tmp_path):
    ken_dir = _paths.ken_dir(tmp_path)
    ken_dir.mkdir()
    _paths.meta_path(tmp_path).write_text(
        json.dumps({"project_id": "proj-status", "auth_token": "tok"}),
        encoding="utf-8",
    )
    with connect(_paths.db_path(tmp_path)) as conn:
        init_schema(conn)
    return tmp_path


def test_status_prints_index_memory_and_daemon_counts(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    now_ms = int(time.time() * 1000)
    emb = vec_to_blob(np.ones(384, dtype=np.float32))
    with connect(_paths.db_path(root)) as conn:
        cur = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
            "VALUES ('src/a.py', 'python', ?, ?, ?, ?)",
            (b"\x00" * 32, int(time.time() * 1e9), now_ms, emb),
        )
        file_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, embedding) "
            "VALUES (?, 'function', 'a', 'a', 1, 2, ?)",
            (file_id, emb),
        )
        sess = conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('agent', ?)",
            (now_ms,),
        ).lastrowid
        conn.execute(
            "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
            "VALUES (?, 'user_prompt', 'inspect a', 1, ?, ?)",
            (sess, emb, now_ms),
        )
        conn.execute(
            "INSERT INTO cr_interactions(session_id, iteration, event_type, target_kind, target_path, weight, created_at) "
            "VALUES (?, 1, 'read', 'file', 'src/a.py', 1.0, ?)",
            (sess, now_ms),
        )
        conn.execute(
            "INSERT INTO cr_session_scores(session_id, target_kind, target_path, score, pattern, created_at) "
            "VALUES (?, 'file', 'src/a.py', 1.0, 'read_edit', ?)",
            (sess, now_ms),
        )
        conn.execute(
            "INSERT INTO cr_findings(topic, content, tags, embedding, created_at, updated_at) "
            "VALUES ('status', 'status finding', '[]', ?, ?, ?)",
            (emb, now_ms, now_ms),
        )

    monkeypatch.setattr(
        "ken.daemon.client.health",
        lambda _root: {"sessions_active": 1, "idle_s": 2.5},
    )

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "files indexed : 1 (1 embedded)" in out
    assert "symbols       : 1 (1 embedded)" in out
    assert "sessions      : 1 total, 1 active, 1 scored" in out
    assert "contexts      : 1 (1 prompts, 1 embedded)" in out
    assert "interactions  : 1" in out
    assert "findings      : 1 (1 embedded)" in out
    assert "rank signals  : index=yes, embeddings=ready, predictive=yes, findings=yes" in out
    assert "embedding cov : 2/2 (100.0%)" in out
    assert "daemon        : running (sessions=1, idle=2.5s)" in out


def test_status_report_is_machine_readable(monkeypatch, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    report = status_report(root)

    assert report["ok"] is True
    assert report["project_root"] == str(root)
    assert report["installed"] is True
    assert report["counts"]["files"] == 0
    assert report["rank_signals"] == {
        "index": "empty",
        "embeddings": "none",
        "predictive": "no",
        "findings": "no",
    }
    assert report["embedding_coverage"] == {"embedded": 0, "total": 0, "percent": 0.0}
    assert report["recommendations"] == [
        "run `ken install .` or re-run it to populate the code index",
        "submit at least one prompt through a hooked agent to seed context history",
        "let hooks run through a few real turns to build predictive history",
        "save reusable project facts with `ken remember TOPIC CONTENT`",
    ]
    assert report["daemon"] == {"running": False}


def test_status_json_prints_report(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root, as_json=True)

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["rank_signals"]["index"] == "empty"


def test_status_prints_stopped_daemon(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    assert rc == 0
    assert "daemon        : stopped" in capsys.readouterr().out


def test_status_rank_signals_show_missing_history(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    assert rc == 0
    assert (
        "rank signals  : index=empty, embeddings=none, predictive=no, findings=no"
        in capsys.readouterr().out
    )


def test_status_prints_recommendations(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "recommendation: run `ken install .`" in out
    assert "recommendation: let hooks run through a few real turns" in out


def test_status_recommends_tool_hook_check_when_prompts_have_no_interactions(
    monkeypatch, capsys, tmp_path
):
    root = _installed_project(tmp_path)
    now_ms = int(time.time() * 1000)
    emb = vec_to_blob(np.ones(384, dtype=np.float32))
    with connect(_paths.db_path(root)) as conn:
        sess = conn.execute(
            "INSERT INTO cr_sessions(agent_id, started_at) VALUES ('agent', ?)",
            (now_ms,),
        ).lastrowid
        conn.execute(
            "INSERT INTO cr_contexts(session_id, kind, content, iteration, embedding, created_at) "
            "VALUES (?, 'user_prompt', 'inspect a', 1, ?, ?)",
            (sess, emb, now_ms),
        )
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "verify tool hooks are recording reads/edits" in out


def test_status_reports_partial_embedding_coverage(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    now_ms = int(time.time() * 1000)
    emb = vec_to_blob(np.ones(384, dtype=np.float32))
    with connect(_paths.db_path(root)) as conn:
        embedded = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
            "VALUES ('src/a.py', 'python', ?, ?, ?, ?)",
            (b"\x00" * 32, int(time.time() * 1e9), now_ms, emb),
        ).lastrowid
        conn.execute(
            "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, embedding) "
            "VALUES (?, 'function', 'a', 'a', 1, 2, ?)",
            (embedded, emb),
        )
        plain = conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
            "VALUES ('src/b.py', 'python', ?, ?, ?, NULL)",
            (b"\x01" * 32, int(time.time() * 1e9), now_ms),
        ).lastrowid
        conn.execute(
            "INSERT INTO ci_symbols(file_id, kind, name, qualname, line_start, line_end, embedding) "
            "VALUES (?, 'function', 'b', 'b', 1, 2, NULL)",
            (plain,),
        )
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "rank signals  : index=yes, embeddings=partial(2/4)" in out
    assert "embedding cov : 2/4 (50.0%)" in out
    assert "embeddings are partial" in out


def test_status_json_includes_embedding_coverage(monkeypatch, tmp_path):
    root = _installed_project(tmp_path)
    now_ms = int(time.time() * 1000)
    emb = vec_to_blob(np.ones(384, dtype=np.float32))
    with connect(_paths.db_path(root)) as conn:
        conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at, embedding) "
            "VALUES ('src/a.py', 'python', ?, ?, ?, ?)",
            (b"\x00" * 32, int(time.time() * 1e9), now_ms, emb),
        )
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    report = status_report(root)

    assert report["embedding_coverage"] == {"embedded": 1, "total": 1, "percent": 100.0}


def test_status_json_reports_missing_project(capsys, tmp_path):
    rc = show_status(tmp_path, as_json=True)

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "no ken project" in out["error"]
