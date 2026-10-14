from __future__ import annotations

import numpy as np
import pytest

from ken.db import connect, init_schema
from ken.embedder import vec_to_blob
from ken.grep import grep, _safe_terms
from ken.search import search_symbols


def project(tmp_path):
    source = tmp_path / "auth.py"
    source.write_text("def clear_auth():\n    return 'Authorization foo.bar C++ OR'\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    conn.execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at) "
                 "VALUES ('auth.py','python',?,0,0)", (b"x" * 32,))
    fid = conn.execute("SELECT id FROM ci_files").fetchone()["id"]
    for name in ("Other.clear_auth", "Client.clear_auth"):
        conn.execute("INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,embedding) "
                     "VALUES (?,'method','clear_auth',?,1,2,?)",
                     (fid, name, vec_to_blob(np.array([0.6, 0.8], dtype=np.float32))))
    conn.commit()
    return conn


@pytest.mark.parametrize("query", ["Where is Authorization removed?", '"Authorization"?',
                                  "(foo.bar)", "C++", "OR", "clear_auth -> Authorization"])
def test_question_mark_and_quotes_are_safe_fts_input(tmp_path, query):
    with project(tmp_path) as conn:
        result = grep(conn, query, mode="bm25", project_root=tmp_path)
    assert result["ok"], result


def test_query_preserves_negation_and_identifier_text():
    assert _safe_terms("no quitar Authorization?") == ['"no"', '"quitar"', '"Authorization?"']
    assert _safe_terms("do not clear_auth") == ['"do"', '"not"', '"clear_auth"']


def test_unique_exact_symbol_outside_dense_pool_is_first(tmp_path, monkeypatch):
    monkeypatch.setattr("ken.search._query_vec", lambda _: np.array([1.0, 0.0], dtype=np.float32))
    # The exact symbol exists in SQL but is absent from the dense candidate pool.
    monkeypatch.setattr("ken.search._scored_from_store", lambda *args: [])
    with project(tmp_path) as conn:
        results = search_symbols(conn, "Client.clear_auth", project_root=tmp_path)
    assert results[0]["qualname"] == "Client.clear_auth"
    assert results[0]["match"] == "exact"
    assert results[0]["score"] == pytest.approx(0.6)


def test_ambiguous_short_name_keeps_multiple_owners(tmp_path, monkeypatch):
    monkeypatch.setattr("ken.search._query_vec", lambda _: np.array([1.0, 0.0], dtype=np.float32))
    monkeypatch.setattr("ken.search._scored_from_store", lambda *args: [])
    with project(tmp_path) as conn:
        results = search_symbols(conn, "clear_auth", project_root=tmp_path)
    assert {r["qualname"] for r in results} == {"Other.clear_auth", "Client.clear_auth"}
