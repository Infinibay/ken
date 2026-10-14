from __future__ import annotations

from pathlib import Path

import pytest

from ken.db import connect, init_schema
from ken.indexer import index_files


def indexed(tmp_path):
    source = tmp_path / "auth.py"
    source.write_text("def outer():\n    def inner():\n        return 'Authorization'\n    return inner\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("auth.py")])
    return conn


def test_unchanged_bytes_reindex_when_tokenizer_or_budget_changes(tmp_path):
    from ken.retrieval.passages import PassagePolicy
    from ken.retrieval.storage import generation
    conn = indexed(tmp_path)
    before = generation(conn)
    policy = PassagePolicy(max_tokens=8, tokenizer_version="actual-model-tokenizer-v1")
    stats = index_files(conn, tmp_path, [Path("auth.py")], retrieval_policy=policy)
    assert stats.parsed == 1
    assert generation(conn) > before
    again = index_files(conn, tmp_path, [Path("auth.py")], retrieval_policy=policy)
    assert again.unchanged == 1
    row = conn.execute("SELECT tokenizer_version,max_tokens FROM ci_retrieval_files").fetchone()
    assert tuple(row) == (policy.tokenizer_version, 8)


def test_indexer_persists_passages_and_canonical_nested_identity(tmp_path):
    from ken.retrieval.storage import load_passages
    with indexed(tmp_path) as conn:
        passages = load_passages(conn)
        assert passages
        assert any(p.entity.qualname == "outer.inner" for p in passages)
        symbols = {r["qualname"] for r in conn.execute("SELECT qualname FROM ci_symbols")}
        assert {p.entity.qualname for p in passages if p.entity.qualname} <= symbols
        assert index_files(conn, tmp_path, [Path("auth.py")]).unchanged == 1


def test_edit_delete_and_parser_change_invalidate_passages(tmp_path, monkeypatch):
    from ken.retrieval.storage import load_passages, generation
    with indexed(tmp_path) as conn:
        before = generation(conn)
        (tmp_path / "auth.py").write_text("def changed():\n    return 'new secret'\n")
        index_files(conn, tmp_path, [Path("auth.py")])
        assert generation(conn) > before
        assert all(p.entity.qualname != "outer.inner" for p in load_passages(conn))
        assert any("new secret" in p.fields["body"] for p in load_passages(conn))
        monkeypatch.setattr("ken.indexer.PARSER_VERSION", 999)
        assert index_files(conn, tmp_path, [Path("auth.py")]).parsed == 1
        before = generation(conn)
        conn.execute("DELETE FROM ci_files WHERE path='auth.py'")
        assert not load_passages(conn)
        assert generation(conn) > before


def test_failure_does_not_publish_partial_generation(tmp_path, monkeypatch):
    from ken.retrieval import storage
    with indexed(tmp_path) as conn:
        before = storage.load_passages(conn)
        epoch = storage.generation(conn)
        (tmp_path / "auth.py").write_text("def changed():\n    return 'new'\n")
        def fail(*args, **kwargs):
            raise RuntimeError("simulated publication failure")
        monkeypatch.setattr(storage, "replace_file_passages", fail)
        with pytest.raises(RuntimeError, match="publication failure"):
            index_files(conn, tmp_path, [Path("auth.py")])
        assert storage.load_passages(conn) == before
        assert storage.generation(conn) == epoch
        assert conn.execute("SELECT name FROM ci_symbols ORDER BY line_start").fetchone()["name"] == "outer"


def test_legacy_database_migrates_without_losing_findings(tmp_path):
    from ken.retrieval.storage import load_passages
    conn = connect(tmp_path / "old.db")
    init_schema(conn)
    conn.execute("INSERT INTO meta(key,value) VALUES ('test_user_data','preserve')")
    init_schema(conn)
    assert load_passages(conn) == []
    assert conn.execute("SELECT value FROM meta WHERE key='test_user_data'").fetchone()[0] == "preserve"
    conn.close()
