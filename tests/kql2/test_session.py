"""Prepared readers preserve source revisions and per-query execution state."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import json

import pytest

from ken import kql2


QUERY = '''language "kql/2"; module session_test;
query q {class $c {name:"Worker";} select $c.name,$c.path;}
'''
NESTED = '''language "kql/2"; module session_test;
predicate Named(TypeDecl $c) {$c.name == "Worker"}
predicate Inner(TypeDecl $c) {Named($c)}
predicate Outer(TypeDecl $c) {Inner($c)}
query q {class $c {name:"Worker";} where Outer($c); select $c.name,$c.path;}
'''


def test_public_session_runs_selective_and_nested_queries(tmp_path: Path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    session_type = getattr(kql2, 'QuerySession', None)
    assert session_type is not None, 'KQL2 must expose its prepared query session'
    with session_type(tmp_path) as session:
        for query in (QUERY, NESTED, QUERY):
            result = session.search(query)
            assert result['rows'] == [['Worker', 'a.py']]
            assert result['complete'] is True
            assert result['coverage_complete'] is True
            assert result['unknown_candidates'] == 0
            assert result['analysis']['parsed_units'] == 0
            assert result['analysis']['reused_units'] == 1
            assert result['analysis']['result_cache'] == 'disabled'


def test_novel_queries_do_not_reopen_storage_or_recapture_files(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import session as module
    from ken.structural_store import artifacts

    with kql2.QuerySession(tmp_path) as session:
        def forbidden(*args, **kwargs):
            pytest.fail('a prepared query reopened storage or recaptured sources')
        monkeypatch.setattr(module, 'search', forbidden)
        monkeypatch.setattr(sqlite3, 'connect', forbidden)
        monkeypatch.setattr(artifacts, 'read_existing', forbidden)
        for i in range(3):
            assert session.search(QUERY.replace('session_test', f'novel_{i}'))['rows'] == [['Worker', 'a.py']]


def test_refresh_uses_bytes_and_preserves_previous_reader(tmp_path):
    source = tmp_path / 'a.py'
    source.write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as first, kql2.QuerySession(tmp_path) as second:
        original = first.search(QUERY)['analysis']['snapshot']
        before = source.stat()
        source.write_text('class Warker: pass\n')
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        second.refresh()
        assert second.search(QUERY)['rows'] == []
        assert second.search(QUERY.replace('Worker', 'Warker'))['rows'] == [['Warker', 'a.py']]
        assert first.search(QUERY)['rows'] == [['Worker', 'a.py']]
        assert first.search(QUERY)['analysis']['snapshot'] == original
        (tmp_path / 'b.py').write_text('class Worker: pass\n')
        source.unlink()
        second.refresh()
        assert second.search(QUERY)['rows'] == [['Worker', 'b.py']]


def test_invalidation_requires_refresh_before_next_query(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        session.invalidate()
        with pytest.raises(RuntimeError, match='refresh'):
            session.search(QUERY)
        session.refresh()
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_capture_is_protected_until_reader_is_pinned(tmp_path, monkeypatch):
    source = tmp_path / 'a.py'
    source.write_text('class Worker: pass\n')
    from ken.kql2 import session as module
    original = module.search

    def concurrent_publications(*args, **kwargs):
        captured = original(*args, **kwargs)
        for name in ('First', 'Second', 'Third'):
            source.write_text(f'class {name}: pass\n')
            original(tmp_path, QUERY)
        return captured

    monkeypatch.setattr(module, 'search', concurrent_publications)
    with kql2.QuerySession(tmp_path) as session:
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_invalidation_during_refresh_does_not_publish_ready_state(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import session as module
    with kql2.QuerySession(tmp_path) as session:
        original = module.search
        def changed(*args, **kwargs):
            captured = original(*args, **kwargs)
            session.invalidate()
            return captured
        monkeypatch.setattr(module, 'search', changed)
        with pytest.raises(RuntimeError, match='refresh'):
            session.refresh()
        with pytest.raises(RuntimeError, match='refresh'):
            session.search(QUERY)


def test_closed_session_cannot_be_reopened_and_releases_lease(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    session = kql2.QuerySession(tmp_path)
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match='closed'):
        session.search(QUERY)
    with pytest.raises(RuntimeError, match='closed'):
        session.refresh()
    with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
        assert db.execute('SELECT count(*) FROM k2_leases').fetchone()[0] == 0


def test_session_requires_its_own_thread(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session, ThreadPoolExecutor(1) as worker:
        with pytest.raises(RuntimeError, match='thread'):
            worker.submit(session.search, QUERY).result()
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


@pytest.mark.parametrize('options,reason', [
    ({'max_states': 1}, 'max_states'),
    ({'timeout_ms': 0}, 'timeout'),
    ({'cancelled': lambda: True}, 'cancelled'),
])
def test_query_budget_does_not_contaminate_next_execution(tmp_path, options, reason):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        interrupted = session.search(NESTED, **options)
        assert interrupted['complete'] is False
        assert interrupted['reason'] == reason
        assert session.search(NESTED)['rows'] == [['Worker', 'a.py']]
        assert session.search(NESTED)['complete'] is True


def test_supplied_libraries_and_entry_points_are_part_of_plan_key(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\nclass Other: pass\n')
    library = '''language "kql/2"; module filters;
pattern Choose(out TypeDecl $c) {class $c {name:"Worker";}}
'''
    query = '''language "kql/2"; module main; import filters;
query one {use filters.Choose(c:$c); select $c.name;}
query two {select 2;}
'''
    with kql2.QuerySession(tmp_path) as session:
        assert session.search(query, query_name='one', libraries={'filters': library})['rows'] == [['Worker']]
        assert session.search(query, query_name='one', libraries={'filters': library.replace('Worker', 'Other')})['rows'] == [['Other']]
        assert session.search(query, query_name='two', libraries={'filters': library})['rows'] == [[2]]


def test_profile_reference_and_diagnostics_remain_public(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        actual = session.search(QUERY, profile=True)
        assert actual['analysis']['operator_profile']
        assert session.search(QUERY, reference=True)['rows'] == [['Worker', 'a.py']]
        text = 'language "kql/2"; module advice; query q {callable $f {} callable $g {} select $f;} '
        advised = session.search(text)
        assert advised.get('diagnostics')


def test_reused_incomplete_unit_keeps_coverage_unknown(tmp_path):
    (tmp_path / 'a.py').write_text('class Broken(:\n pass\n')
    with kql2.QuerySession(tmp_path) as session:
        assert session.search(QUERY)['coverage_complete'] is False
        session.refresh()
        assert session.search(QUERY)['coverage_complete'] is False


def test_expired_session_does_not_read_unprotected_snapshot(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
            db.execute('UPDATE k2_leases SET expires_ns=0')
        result = session.search(QUERY)
        assert result['complete'] is False
        assert result['reason'] == 'snapshot_expired'
        session.refresh()
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_json_response_includes_completed_execution_and_budget(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        response = json.loads(session.search_json(NESTED))
        assert response['rows'] == [['Worker', 'a.py']]
        assert response['complete'] is True
        assert response['analysis']['build_ms'] == 0
        interrupted = json.loads(session.search_json(NESTED, timeout_ms=0))
        assert interrupted['complete'] is False
        assert interrupted['reason'] == 'timeout'


def test_explicit_scope_and_entity_locations(tmp_path):
    (tmp_path / 'a.py').write_text('def save():\n return 1\n')
    (tmp_path / 'b.py').write_text('def unrelated():\n return 2\n')
    query = 'language "kql/2"; module test; query q {edge ENTITY($f,"CALLABLE"); select $f;}'
    with kql2.QuerySession(tmp_path, source_paths=['a.py']) as session:
        session.prepare_graph()
        response = session.search(query, include_entities=True)
        assert len(response['rows']) == 1
        identity = response['rows'][0][0]
        assert response['entities'][identity] == {'local_id':identity, 'kind':'CALLABLE', 'name':'save', 'path':'a.py', 'line':1}
        assert response['source_scope'] == {'kind':'explicit_files', 'paths':['a.py']}
        assert response['plan'][0]['graph_disk_hit'] is True


def test_packaged_libraries_are_captured_and_refreshed(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\nclass Other: pass\n')
    from ken.kql2 import catalog
    definition = '''language "kql/2"; module ken.catalog.fixture;
pattern Choose(out TypeDecl $c) {class $c {name:"Worker";}}
'''
    def snapshots():
        return (('fixture.toml', 'query = """' + definition + '"""'),)
    monkeypatch.setattr(catalog, 'sources', snapshots)
    query = 'language "kql/2"; module main; import ken.catalog.fixture; query q {use ken.catalog.fixture.Choose(c:$c); select $c.name;}'
    with kql2.QuerySession(tmp_path) as session:
        definition = definition.replace('Worker', 'Other')
        assert session.search(query)['rows'] == [['Worker']]
        session.refresh()
        assert session.search(query)['rows'] == [['Other']]


def test_invalid_budgets_and_queries_leave_session_usable(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        for options in ({'timeout_ms':-1}, {'timeout_ms':float('nan')}, {'max_rows':0}, {'max_states':0}):
            with pytest.raises(ValueError):
                session.search(QUERY, **options)
        with pytest.raises(ValueError):
            session.search(QUERY.replace('select $c.name,$c.path', 'select $missing'))
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_preparation_requires_retained_storage(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with pytest.raises(ValueError, match='storage'):
        kql2.QuerySession(tmp_path, cache_mb=0)
    assert not (tmp_path / '.ken').exists()


def test_service_accepts_prepared_session_without_recapturing(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import service
    with kql2.QuerySession(tmp_path) as session:
        def forbidden(*args, **kwargs):
            pytest.fail('the prepared service path recaptured files')
        monkeypatch.setattr(service, 'iter_files', forbidden)
        result = service.search(tmp_path, NESTED, session=session, timeout_ms=10)
        assert result['rows'] == [['Worker', 'a.py']]
        assert result['complete'] is True
        assert result['analysis']['result_cache'] == 'disabled'
        with pytest.raises(ValueError, match='scope'):
            service.search(tmp_path, QUERY, path='a.py', session=session)


def test_failed_refresh_preserves_previous_reader_and_releases_new_lease(tmp_path, monkeypatch):
    source = tmp_path / 'a.py'
    source.write_text('class Worker: pass\n')
    from ken.kql2 import catalog
    with kql2.QuerySession(tmp_path) as session:
        source.write_text('class Other: pass\n')
        monkeypatch.setattr(catalog, 'sources', lambda: (('bad.toml','[invalid'),))
        with pytest.raises(ValueError):
            session.refresh()
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
            assert db.execute('SELECT count(*) FROM k2_leases').fetchone()[0] == 1


def test_session_inherits_existing_request_deadline(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2.request import supervised
    with kql2.QuerySession(tmp_path) as session:
        with supervised(0):
            result = session.search(QUERY)
        assert result['complete'] is False
        assert result['reason'] == 'timeout'
        assert session.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_frontend_failure_does_not_count_an_unretained_unit(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import service
    def unavailable(*args, **kwargs):
        raise RuntimeError('native frontend unavailable')
    monkeypatch.setattr(service, 'lower_source', unavailable)
    with kql2.QuerySession(tmp_path) as session:
        result = session.search(QUERY)
        assert result['rows'] == []
        assert result['coverage_complete'] is False
        assert result['analysis']['reused_units'] == 0


@pytest.mark.parametrize('as_json', [False, True])
def test_invalidation_during_compilation_marks_delivery_incomplete(tmp_path, monkeypatch, as_json):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import session as module
    with kql2.QuerySession(tmp_path) as session:
        original = module.compile_query
        def changed(*args, **kwargs):
            prepared = original(*args, **kwargs)
            with ThreadPoolExecutor(1) as watcher:
                watcher.submit(session.invalidate).result()
            return prepared
        monkeypatch.setattr(module, 'compile_query', changed)
        result = json.loads(session.search_json(QUERY)) if as_json else session.search(QUERY)
        assert result['complete'] is False
        assert result['reason'] == 'snapshot_invalidated'
        with pytest.raises(RuntimeError, match='refresh'):
            session.search(QUERY)


@pytest.mark.parametrize('as_json', [False, True])
def test_inherited_deadline_covers_reporting(tmp_path, monkeypatch, as_json):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import diagnostics, request
    original = diagnostics.diagnose
    def expire(program):
        result = original(program)
        request._ACTIVE.get().deadline = 0
        return result
    with kql2.QuerySession(tmp_path) as session:
        monkeypatch.setattr(diagnostics, 'diagnose', expire)
        with request.supervised(10000):
            result = json.loads(session.search_json(QUERY)) if as_json else session.search(QUERY)
        assert result['complete'] is False
        assert result['reason'] == 'timeout'


@pytest.mark.parametrize('change', ['timeout', 'inherited_timeout', 'invalidate'])
def test_json_delivery_checks_after_encoding(tmp_path, monkeypatch, change):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import request, session as module
    from types import SimpleNamespace
    from contextlib import nullcontext
    now = [0.0]
    with kql2.QuerySession(tmp_path) as session:
        original = json.dumps
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0], time_ns=__import__('time').time_ns))
        calls = [0]
        def changed(*args, **kwargs):
            encoded = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 2:
                if change == 'timeout':
                    now[0] += .011
                elif change == 'inherited_timeout':
                    request._ACTIVE.get().deadline = 0
                else:
                    session.invalidate()
            return encoded
        monkeypatch.setattr(module, 'json', SimpleNamespace(dumps=changed))
        context = request.supervised(10000) if change == 'inherited_timeout' else nullcontext()
        with context:
            result = json.loads(session.search_json(QUERY, timeout_ms=10 if change == 'timeout' else None))
        assert result['complete'] is False
        assert result['reason'] == ('snapshot_invalidated' if change == 'invalidate' else 'timeout')
        if change == 'timeout':
            assert result['analysis']['total_ms'] >= 11


def test_close_releases_connection_when_lease_cleanup_is_locked(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    session = kql2.QuerySession(tmp_path)
    reader = session._store
    writer = sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite')
    try:
        reader.db.execute('PRAGMA busy_timeout=0')
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            session.close()
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            reader.db.execute('SELECT 1')
        session.close()
    finally:
        writer.rollback()
        writer.close()
        reader.db.close()


def test_expired_reader_cannot_prepare_graph(tmp_path):
    (tmp_path / 'a.py').write_text('def save(): return 1\n')
    from ken.structural_store.leases import SnapshotExpired
    with kql2.QuerySession(tmp_path) as session:
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
            db.execute('UPDATE k2_leases SET expires_ns=0')
        with pytest.raises(SnapshotExpired):
            session.prepare_graph()


def test_lease_renewal_does_not_wait_for_another_writer(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        reader = session._store
        assert reader.db.execute('PRAGMA busy_timeout').fetchone()[0] == 0
        reader.lease_renew_at = 0
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as writer:
            writer.execute('BEGIN IMMEDIATE')
            result = session.search(NESTED, timeout_ms=10)
            assert result['complete'] is True
            assert result['rows'] == [['Worker', 'a.py']]
            writer.rollback()
        assert session.search(QUERY)['complete'] is True


def test_expired_lease_is_not_revived_under_write_contention(tmp_path):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with kql2.QuerySession(tmp_path) as session:
        assert session._store.db.execute('PRAGMA busy_timeout').fetchone()[0] == 0
        session._store.lease_renew_at = 0
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as writer:
            writer.execute('UPDATE k2_leases SET expires_ns=0')
            writer.commit()
            writer.execute('BEGIN IMMEDIATE')
            result = session.search(QUERY)
            assert result['complete'] is False
            assert result['reason'] == 'snapshot_expired'
            assert result['rows'] == []
            writer.rollback()


def test_json_total_includes_successful_encoding(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import session as module
    from types import SimpleNamespace
    import time
    now = [0.0]
    with kql2.QuerySession(tmp_path) as session:
        original = json.dumps
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: now[0], time_ns=time.time_ns))
        def encode(*args, **kwargs):
            text = original(*args, **kwargs)
            now[0] += .003
            return text
        monkeypatch.setattr(module, 'json', SimpleNamespace(dumps=encode))
        result = json.loads(session.search_json(QUERY, timeout_ms=10))
        assert result['complete'] is True
        assert result['analysis']['total_ms'] == pytest.approx(6.0)


def test_reporting_reserve_does_not_shorten_delivery_deadline(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.kql2 import diagnostics, request
    from types import SimpleNamespace
    original = diagnostics.diagnose
    def nearly_finished(program):
        result = original(program)
        request._ACTIVE.get().deadline = .025
        return result
    with kql2.QuerySession(tmp_path) as session:
        monkeypatch.setattr(request, 'time', SimpleNamespace(monotonic=lambda: 0.0))
        monkeypatch.setattr(diagnostics, 'diagnose', nearly_finished)
        with request.supervised(10000):
            result = json.loads(session.search_json(QUERY))
        assert result['complete'] is True
        assert result['reason'] is None


def test_prepared_graph_uses_nonblocking_lease_policy(tmp_path):
    (tmp_path / 'a.py').write_text('def save(): return 1\n')
    query = 'language "kql/2"; module graph; query q {edge ENTITY($f,"CALLABLE"); select $f;}'
    with kql2.QuerySession(tmp_path) as session:
        session.prepare_graph()
        session._store.lease_renew_at = 0
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as writer:
            writer.execute('BEGIN IMMEDIATE')
            result = session.search(query, include_entities=True)
            assert result['complete'] is True
            assert len(result['rows']) == 1
            identity = result['rows'][0][0]
            assert result['entities'][identity]['name'] == 'save'
            assert result['plan'][0]['graph_disk_hit'] is True
            writer.rollback()


def test_deferred_renewal_rechecks_expiry_after_busy(tmp_path, monkeypatch):
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    from ken.structural_store import leases
    from types import SimpleNamespace
    import time
    now = [0]
    with kql2.QuerySession(tmp_path) as session:
        reader = session._store
        db = reader.db
        db.execute('UPDATE k2_leases SET expires_ns=100')
        reader.lease_renew_at = 0
        class BusyAfterExpiry:
            def execute(self, sql, parameters):
                if sql.startswith('UPDATE'):
                    now[0] = 200
                    error = sqlite3.OperationalError('database is locked')
                    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise error
                return db.execute(sql, parameters)
        monkeypatch.setattr(leases, 'time', SimpleNamespace(time_ns=lambda: now[0], monotonic=time.monotonic))
        reader.db = BusyAfterExpiry()
        try:
            with pytest.raises(leases.SnapshotExpired):
                leases.renew(reader)
        finally:
            reader.db = db
