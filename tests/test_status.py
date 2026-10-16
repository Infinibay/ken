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
        conn.execute(
            "INSERT INTO ci_intent_sources(file_id, source_kind, text, embedding, updated_at) "
            "VALUES (?, 'module_docstring', 'Status diagnostics.', ?, ?)",
            (file_id, emb, now_ms),
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
    # Inventory stays available in JSON; default text focuses on index health.
    assert status_report(root)["counts"] == {
        "files": 1, "files_embedded": 1, "symbols": 1, "symbols_embedded": 1,
        "sessions": 1, "active_sessions": 1, "contexts": 1, "prompt_contexts": 1,
        "prompt_contexts_embedded": 1, "interactions": 1, "session_scores": 1,
        "findings": 1, "findings_embedded": 1, "intent_sources": 1, "intent_sources_embedded": 1,
    }
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
    assert "files indexed : 0 (0 embedded)" in capsys.readouterr().out
    assert status_report(root)["rank_signals"] == {
        "index": "empty", "embeddings": "none", "predictive": "no", "findings": "no"}


def test_status_prints_recommendations(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "recommendation: run `ken install .`" in out
    assert "let hooks run through a few real turns" not in out


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
    assert status_report(root)["rank_signals"]["embeddings"] == "partial(2/4)"
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


def test_status_reports_stale_indexed_files(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    now_ms = int(time.time() * 1000)
    live = root / "src" / "live.py"
    live.parent.mkdir()
    live.write_text("def live(): return 1\n")
    with connect(_paths.db_path(root)) as conn:
        conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
            "VALUES ('src/live.py', 'python', ?, ?, ?)",
            (b"\x00" * 32, int(time.time() * 1e9), now_ms),
        )
        conn.execute(
            "INSERT INTO ci_files(path, language, content_hash, mtime, indexed_at) "
            "VALUES ('src/stale.py', 'python', ?, ?, ?)",
            (b"\x01" * 32, int(time.time() * 1e9), now_ms),
        )
    monkeypatch.setattr("ken.daemon.client.health", lambda _root: None)

    rc = show_status(root)

    out = capsys.readouterr().out
    assert rc == 0
    assert "index health  : 1 stale files (src/stale.py)" in out
    assert "indexed files are missing on disk" in out
    report = status_report(root)
    assert report["index_health"] == {"stale_files": 1, "sample": ["src/stale.py"]}


def test_status_json_reports_missing_project(capsys, tmp_path):
    rc = show_status(tmp_path, as_json=True)

    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "no ken project" in out["error"]


def test_default_status_omits_internal_inventory_but_json_retains_it(monkeypatch, capsys, tmp_path):
    root = _installed_project(tmp_path)
    monkeypatch.setattr('ken.daemon.client.health', lambda _root: None)
    assert show_status(root) == 0
    text = capsys.readouterr().out
    assert 'files indexed' in text and 'symbols' in text and 'stopped' in text
    assert 'project_id' not in text and 'db ' not in text
    assert 'sessions ' not in text and 'contexts ' not in text and 'interactions ' not in text
    assert 'seed context history' not in text and 'few real turns' not in text
    assert 'run `ken install .' in text
    assert show_status(root, as_json=True) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['project_id'] == 'proj-status' and 'db' in data
    assert data['counts']['sessions'] == 0 and data['counts']['interactions'] == 0
