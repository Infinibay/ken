"""Preparation demand, spill failures and isolation across prepared evaluations."""

import sqlite3

import pytest

from ken.kql2.semantic_index import SemanticIndex
from ken.kql2.session import QuerySession, SourcesChanged
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural_store import Store


SOURCE = '''def resolve(value): return value
def work(first, second) -> int:
    return resolve(first)
'''

BODY = '''language "kql/2"; module isolated;
query q { callable $f {name:"work"; param $input {name:"first";} body {
    let $result = call $site {name:"resolve"; argument $input at 0;};
    return $result;
}} select $f.name; }
'''


@pytest.mark.parametrize(
    "constraint",
    [
        'callable $f {name:"work";return_type_status:known;}',
        'callable $f {name:"work";} where $f.return_type_status == "known";',
    ],
)
def test_semantic_status_queries_prepare_and_reuse_their_facts(
    tmp_path, monkeypatch, constraint
):
    from ken.kql2 import semantic

    (tmp_path / "a.py").write_text(SOURCE)
    query = 'language "kql/2";module status;query q{' + constraint + 'select $f.name;}'
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(query)
        retained = session._semantic_index
        session.invalidate()
        session.refresh()
        assert session._semantic_index is retained

        def forbidden(*args, **kwargs):
            pytest.fail("semantic status was linked inside the prepared query")

        monkeypatch.setattr(semantic, "link_project", forbidden)
        result = session.search(query)
        assert result["complete"] and result["unknown_candidates"] == 0
        assert result["rows"] == [["work"]]


def test_graph_body_terminal_reuses_private_preparation_when_shared_cache_is_full(
    tmp_path, monkeypatch
):
    from ken.kql2 import graph_execution

    (tmp_path / "a.py").write_text(SOURCE)
    query = '''language "kql/2";module terminal;
    query q {callable $f {name:"work";param $x {name:"first";}body {
      call $r {name:"resolve";};
      gap until exit {forbid assign(binding($x));}
    }} select $f;}
    '''
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(query)

        retained = session._graph_index
        session.invalidate()
        session.refresh()
        assert session._graph_index is retained

        def forbidden(*args, **kwargs):
            pytest.fail("a prepared terminal BODY linked the project again")

        monkeypatch.setattr(graph_execution, "link_project", forbidden)
        for _ in range(2):
            result = session.search(query)
            assert result["complete"] and result["unknown_candidates"] == 0
            assert len(result["rows"]) == 1


def test_failed_spill_closes_its_private_database(tmp_path, monkeypatch):
    from ken.kql2 import semantic_index

    opened = []
    connect = sqlite3.connect

    def track(database, *args, **kwargs):
        db = connect(database, *args, **kwargs)
        if database == "":
            opened.append(db)
        return db

    def interrupted():
        raise RuntimeError("interrupted spill")

    graph = link_project([lower_source(SOURCE, "python", "a.py")])
    with Store(tmp_path / "store.sqlite", cache_mb=20) as store:
        monkeypatch.setattr(semantic_index.sqlite3, "connect", track)
        with pytest.raises(RuntimeError, match="interrupted spill"):
            SemanticIndex.spill(store.db, 1, graph, interrupted)
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")


def test_invalidation_before_spill_publication_closes_unpublished_index(
    tmp_path, monkeypatch
):
    (tmp_path / "a.py").write_text(SOURCE)
    spill = SemanticIndex.spill.__func__
    opened = []
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes

        def invalidate_before_return(cls, *args, **kwargs):
            index = spill(cls, *args, **kwargs)
            opened.append(index.db)
            session.invalidate()
            return index

        monkeypatch.setattr(SemanticIndex, "spill", classmethod(invalidate_before_return))
        with pytest.raises(SourcesChanged):
            session.prepare_query(BODY)
        assert session._semantic_index is None
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            opened[0].execute("SELECT 1")


def test_private_facts_do_not_share_bindings_or_cancellation(tmp_path, monkeypatch):
    from ken.kql2 import semantic

    (tmp_path / "a.py").write_text(SOURCE)
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(BODY)
        retained = session._semantic_index
        assert retained.storage == "session_disk"

        def forbidden(*args, **kwargs):
            pytest.fail("an isolated prepared query linked again")

        monkeypatch.setattr(semantic, "link_project", forbidden)
        stopped = session.search(BODY, cancelled=lambda: True)
        assert not stopped["complete"] and stopped["reason"] == "cancelled"
        for query, expected in (
            (BODY, [["work"]]),
            (BODY.replace('name:"first"', 'name:"second"'), []),
            (BODY, [["work"]]),
        ):
            result = session.search(query)
            assert result["complete"] and result["unknown_candidates"] == 0
            assert result["rows"] == expected
            assert session._semantic_index is retained
