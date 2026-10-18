"""BODY acquisition belongs to preparation; retained facts are not query answers."""
import sqlite3

import pytest

from ken.kql2.host import QueryHost
from ken.kql2.session import QuerySession


SOURCE = 'def resolve(): return 1\ndef work():\n    return resolve()\n'
QUERY = '''language "kql/2"; module prepared_body;
query q {callable $f {name:"work"; body {
  let $result = call $site {name:"resolve";}; return $result;
}} select $f.name;}
'''


@pytest.mark.parametrize('spill', [False, True])
def test_body_preparation_retains_facts_across_queries_and_closes_owned_storage(tmp_path, monkeypatch, spill):
    (tmp_path / 'a.py').write_text(SOURCE)
    from ken.kql2 import semantic

    with QuerySession(tmp_path) as session:
        if spill:
            # Compact facts can fit in already allocated free pages. Put the
            # quota strictly below allocation to force the spill boundary.
            session._store.limit_bytes = session._store.allocated_bytes - 1
        session.prepare_query(QUERY)
        index = session._semantic_index
        assert index is not None
        assert index.storage == ('session_disk' if spill else 'shared_disk')
        assert session._store.db.execute('SELECT count(*) FROM k2_analysis').fetchone()[0] == (0 if spill else 1)

        def forbidden(*args, **kwargs):
            pytest.fail('a prepared BODY linked the project again')
        monkeypatch.setattr(semantic, 'link_project', forbidden)
        for text in (QUERY, QUERY.replace('module prepared_body;', 'module another_plan;')):
            result = session.search(text)
            assert result['rows'] == [['work']]
            assert result['complete'] and result['coverage_complete']
            assert result['unknown_candidates'] == 0
            assert result['analysis']['result_cache'] == 'disabled'
        if spill:
            owned_db = index.db
    if spill:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            owned_db.execute('SELECT 1')


def test_host_prepares_body_before_query_deadline_and_rebuilds_after_edits(tmp_path, monkeypatch):
    source = tmp_path / 'a.py'
    source.write_text(SOURCE)
    from ken.kql2 import semantic
    search = QuerySession.search
    def search_after_preparation(session, *args, **kwargs):
        assert session._store.db.execute('SELECT count(*) FROM k2_analysis WHERE snapshot_id=?',
                                        (session._metadata['snapshot'],)).fetchone()[0] == 1
        return search(session, *args, **kwargs)
    monkeypatch.setattr(QuerySession, 'search', search_after_preparation)

    with QueryHost(tmp_path, watch=False) as host:
        first = host.search(QUERY)
        assert first['analysis']['preparation_ms'] > 0
        assert first['rows'] == [['work']] and first['unknown_candidates'] == 0
        original = semantic.link_project
        def forbidden(*args, **kwargs):
            pytest.fail('an unchanged automatic BODY query linked again')
        monkeypatch.setattr(semantic, 'link_project', forbidden)
        repeated = host.search(QUERY)
        assert repeated['analysis']['preparation_ms'] == 0
        assert repeated['rows'] == [['work']]
        monkeypatch.setattr(semantic, 'link_project', original)
        source.write_text(SOURCE.replace('return resolve()', 'return 2'))
        changed = host.search(QUERY)
        assert changed['analysis']['snapshot'] != first['analysis']['snapshot']
        assert changed['analysis']['preparation_ms'] > 0
        assert changed['rows'] == [] and changed['unknown_candidates'] == 0


def test_semantic_spill_refresh_and_query_budget_do_not_leak_state(tmp_path):
    source = tmp_path / 'a.py'
    source.write_text(SOURCE)
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(QUERY)
        private = session._semantic_index.db
        interrupted = session.search(QUERY, timeout_ms=0)
        assert not interrupted['complete'] and interrupted['reason'] == 'timeout'
        assert session.search(QUERY)['rows'] == [['work']]
        source.write_text(SOURCE.replace('return resolve()', 'return 2'))
        session.refresh()
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            private.execute('SELECT 1')
        session.prepare_query(QUERY)
        result = session.search(QUERY)
        assert result['complete'] and result['unknown_candidates'] == 0
        assert result['rows'] == []


def test_new_host_can_reclaim_unleased_cache_before_admitting_reader(tmp_path):
    from ken.structural_store import Store
    from ken.structural_store.artifacts import write
    (tmp_path / 'a.py').write_text(SOURCE)
    with Store(tmp_path / '.ken/structural/v2/store.sqlite', cache_mb=20) as store:
        assert write(store, 'old', 'compiled', 'old-codec', b'x' * 3_000_000)
        assert store.allocated_bytes > 1_000_000
    with QueryHost(tmp_path, watch=False) as host:
        result = host.search(QUERY, cache_mb=1)
        assert result['complete'] and result['rows'] == [['work']]
        assert result['unknown_candidates'] == 0


@pytest.mark.parametrize('spill', [False, True])
def test_unchanged_refresh_retains_prepared_body_and_live_reader(tmp_path, monkeypatch, spill):
    from ken.kql2 import semantic

    (tmp_path / 'a.py').write_text(SOURCE)
    with QuerySession(tmp_path) as session:
        if spill:
            session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(QUERY)
        reader, index = session._store, session._semantic_index
        session.invalidate()
        session.refresh()
        assert session._store is reader
        assert session._semantic_index is index

        def forbidden(*args, **kwargs):
            pytest.fail('refresh of identical sources discarded prepared BODY facts')

        monkeypatch.setattr(semantic, 'link_project', forbidden)
        assert session.prepare_query(QUERY) == 0
        result = session.search(QUERY)
        assert result['complete'] and result['unknown_candidates'] == 0
        assert result['rows'] == [['work']]


def test_unchanged_refresh_replaces_expired_reader_and_closes_private_facts(tmp_path):
    (tmp_path / 'a.py').write_text(SOURCE)
    with QuerySession(tmp_path) as session:
        session._store.limit_bytes = session._store.allocated_bytes
        session.prepare_query(QUERY)
        reader, private = session._store, session._semantic_index.db
        reader.db.execute('UPDATE k2_leases SET expires_ns=0 WHERE lease_id=?', (reader.lease_id,))
        session.refresh()
        assert session._store is not reader
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            private.execute('SELECT 1')
        session.prepare_query(QUERY)
        assert session.search(QUERY)['rows'] == [['work']]


def test_ignored_directory_event_does_not_discard_prepared_body(tmp_path, monkeypatch):
    from ken.kql2 import semantic

    (tmp_path / 'a.py').write_text(SOURCE)
    with QueryHost(tmp_path, watch=False) as host:
        first = host.search(QUERY)
        reader = next(iter(host._readers.values())).session
        retained = reader._semantic_index
        (tmp_path / '__pycache__').mkdir()
        host.resync()

        def forbidden(*args, **kwargs):
            pytest.fail('an ignored-directory event discarded immutable BODY facts')

        monkeypatch.setattr(semantic, 'link_project', forbidden)
        repeated = host.search(QUERY)
        assert repeated['complete'] and repeated['unknown_candidates'] == 0
        assert repeated['rows'] == [['work']]
        assert repeated['analysis']['snapshot'] == first['analysis']['snapshot']
        assert reader._semantic_index is retained
