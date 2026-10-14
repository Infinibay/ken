import math
from pathlib import Path

import pytest

from ken.db import connect, init_schema
from ken.indexer import index_files


def index(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def merge(values):\n    return list(values)\n"
        "def release(values):\n    raise ValueError('COOKIE_JAR_CONFLICT')\n")
    conn = connect(tmp_path / "index.db")
    init_schema(conn)
    index_files(conn, tmp_path, [Path("auth.py")])
    return conn


def test_rare_error_literal_retrieves_implementation(tmp_path):
    from ken.retrieval.lexical import lexical_candidates
    from ken.retrieval.model import SearchRequest
    with index(tmp_path) as conn:
        hits = lexical_candidates(conn, SearchRequest("COOKIE_JAR_CONFLICT"))
        assert hits[0].entity.qualname == "release"
        assert hits[0].signals["bm25f"] > 0
        assert "COOKIE_JAR_CONFLICT" in hits[0].passages[0].fields["body"]


def test_bm25f_matches_hand_calculation():
    from ken.retrieval.lexical import bm25f_score
    result = bm25f_score({"body": 3}, {"body": 20}, {"body": 10.0},
                        document_frequency=2, documents=10)
    tf = 3 / (0.25 + 0.75 * 20 / 10)
    expected = math.log(1 + 8.5 / 2.5) * 2.2 * tf / (1.2 + tf)
    assert result == pytest.approx(expected)
    assert bm25f_score({}, {}, {}, document_frequency=0, documents=0) == 0


def test_delete_updates_document_frequency_and_cached_generation(tmp_path):
    from ken.retrieval.lexical import lexical_candidates
    from ken.retrieval.model import SearchRequest
    with index(tmp_path) as conn:
        assert lexical_candidates(conn, SearchRequest("COOKIE_JAR_CONFLICT"))
        (tmp_path / "auth.py").write_text("def release():\n    return 1\n")
        index_files(conn, tmp_path, [Path("auth.py")])
        assert not lexical_candidates(conn, SearchRequest("COOKIE_JAR_CONFLICT"))
        assert not conn.execute("SELECT 1 FROM ci_passage_terms WHERE term='cookie_jar_conflict'").fetchall()


def test_query_does_not_read_every_source_file(tmp_path, monkeypatch):
    from ken.retrieval.lexical import lexical_candidates
    from ken.retrieval.model import SearchRequest
    with index(tmp_path) as conn:
        def forbidden(*args):
            raise AssertionError("query read a source file")
        monkeypatch.setattr(Path, "read_bytes", forbidden)
        assert lexical_candidates(conn, SearchRequest("COOKIE_JAR_CONFLICT"))


def test_tokenizer_preserves_identifiers_components_and_negation():
    from ken.retrieval.tokenization import code_tokens
    tokens = code_tokens("no eliminar COOKIE_JAR_CONFLICT; do not clearAuth")
    assert {"no", "not", "cookie_jar_conflict", "cookie", "jar", "conflict",
            "clearauth", "clear", "auth"} <= set(tokens)


def test_vectorized_postings_preserve_joint_field_saturation_and_each_field_score():
    from ken.retrieval.lexical import bm25f_score, score_postings
    # pid, field, term, tf, field length: two fields share a term in pid 8.
    rows = [(8, 'identity', 'token', 2, 3), (8, 'body', 'token', 3, 12),
            (8, 'body', 'other', 1, 12), (9, 'body', 'token', 1, 6)]
    averages = {'identity': 3., 'body': 6.}
    scored = score_postings(rows, documents=10, averages=averages)
    expected_token = bm25f_score({'identity':2,'body':3}, {'identity':3,'body':12},
                                averages, document_frequency=2, documents=10)
    expected_other = bm25f_score({'body':1}, {'body':12}, averages, document_frequency=1, documents=10)
    assert scored[8]['bm25f'] == pytest.approx(expected_token+expected_other)
    assert scored[8]['bm25_identity'] == pytest.approx(bm25f_score({'identity':2}, {'identity':3},
        averages, document_frequency=2, documents=10))
    assert scored[8]['bm25_body'] == pytest.approx(bm25f_score({'body':3}, {'body':12},
        averages, document_frequency=2, documents=10)+expected_other)
    assert score_postings([], documents=10, averages=averages) == {}
