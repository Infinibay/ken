"""Automatic query ownership and current source revisions at public boundaries."""

from pathlib import Path
import os

import pytest

QUERY = 'language "kql/2"; module auto; query q {class $c {name:"Worker";} select $c.name,$c.path;}'


def test_host_reuses_reader_and_detects_bytes_with_restored_mtime(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2 import session as session_module
    source = tmp_path / 'a.py'
    source.write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        first = host.search(QUERY)
        assert first['rows'] == [['Worker', 'a.py']]
        original = session_module.search
        def no_recapture(*args, **kwargs):
            pytest.fail('a prepared public query recaptured source bytes')
        monkeypatch.setattr(session_module, 'search', no_recapture)
        assert host.search(QUERY)['analysis']['snapshot'] == first['analysis']['snapshot']
        monkeypatch.setattr(session_module, 'search', original)
        before = source.stat()
        source.write_text('class Warker: pass\n')
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert host.search(QUERY)['rows'] == []
        changed = host.search(QUERY.replace('Worker', 'Warker'))
        assert changed['rows'] == [['Warker', 'a.py']]
        assert changed['analysis']['snapshot'] != first['analysis']['snapshot']
        assert changed['analysis']['result_cache'] == 'disabled'


def test_host_detects_addition_in_empty_directory_and_deletion(tmp_path):
    from ken.kql2.host import QueryHost
    folder = tmp_path / 'empty'
    folder.mkdir()
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY)['rows'] == []
        file = folder / 'new.py'
        file.write_text('class Worker: pass\n')
        assert host.search(QUERY)['rows'] == [['Worker', 'empty/new.py']]
        file.unlink()
        assert host.search(QUERY)['rows'] == []


def test_host_refreshes_source_exclusions(tmp_path):
    from ken.kql2.host import QueryHost
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY)['rows'] == [['Worker', 'a.py']]
        (tmp_path / '.kenignore').write_text('a.py\n')
        assert host.search(QUERY)['rows'] == []
        (tmp_path / '.kenignore').unlink()
        assert host.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_ignored_root_gitignore_still_invalidates_capture(tmp_path):
    from ken.kql2.host import QueryHost
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    config = tmp_path / '.gitignore'
    config.write_text('.gitignore\n')
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY)['rows'] == [['Worker', 'a.py']]
        config.write_text('.gitignore\na.py\n')
        assert host.search(QUERY)['rows'] == []


@pytest.mark.parametrize('scope', ['.', 'pkg'])
def test_ignored_nested_gitignore_remains_a_revision_input(tmp_path, scope):
    from ken.kql2.host import QueryHost
    (tmp_path / '.gitignore').write_text('.gitignore\n')
    folder = tmp_path / 'pkg'
    folder.mkdir()
    (folder / 'a.py').write_text('class Worker: pass\n')
    config = folder / '.gitignore'
    config.write_text('.gitignore\n')
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY, path=scope)['rows'] == [['Worker', 'pkg/a.py']]
        config.write_text('.gitignore\na.py\n')
        assert host.search(QUERY, path=scope)['rows'] == []


def test_graph_is_prepared_before_its_query_budget(tmp_path):
    from ken.kql2.host import QueryHost
    source = tmp_path / 'a.py'
    source.write_text('def save(): return 1\n')
    query = 'language "kql/2"; module graph; query q {edge ENTITY($f,"CALLABLE"); select $f;}'
    with QueryHost(tmp_path, watch=False) as host:
        response = host.search(query, timeout_ms=10, include_entities=True)
        assert response['complete'] is True
        assert response['plan'][0]['graph_disk_hit'] is True
        assert response['entities'][response['rows'][0][0]]['name'] == 'save'
        source.write_text('def other(): return 1\n')
        changed = host.search(query, timeout_ms=10, include_entities=True)
        assert changed['complete'] is True
        assert changed['entities'][changed['rows'][0][0]]['name'] == 'other'


def test_host_does_not_bind_new_stamps_to_old_captured_bytes(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2 import session as session_module
    file = tmp_path / 'a.py'
    file.write_text('class Worker: pass\n')
    original = session_module.search
    calls = [0]
    def changed_during_capture(*args, **kwargs):
        response = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            file.write_text('class Other: pass\n')
        return response
    monkeypatch.setattr(session_module, 'search', changed_during_capture)
    with QueryHost(tmp_path, watch=False) as host:
        response = host.search(QUERY)
        assert response['complete'] is True
        assert response['rows'] == []
        assert calls[0] >= 2


def test_host_retries_after_invalidation_during_query(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2 import session as session_module
    file = tmp_path / 'a.py'
    file.write_text('class Worker: pass\n')
    original = session_module.compile_query
    with QueryHost(tmp_path, watch=False) as host:
        host.search(QUERY)
        calls = [0]
        def changed(*args, **kwargs):
            prepared = original(*args, **kwargs)
            calls[0] += 1
            if calls[0] == 1:
                file.write_text('class Other: pass\n')
                host.resync()
            return prepared
        monkeypatch.setattr(session_module, 'compile_query', changed)
        response = host.search(QUERY)
        assert response['complete'] is True
        assert response['rows'] == []


def test_scopes_and_execution_budgets_are_independent(tmp_path):
    from ken.kql2.host import QueryHost
    for folder in ['one', 'two']:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'a.py').write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(QUERY, path='one')['rows'] == [['Worker', 'one/a.py']]
        assert host.search(QUERY, path='two')['rows'] == [['Worker', 'two/a.py']]
        result = host.search(QUERY, timeout_ms=0)
        assert result['complete'] is False
        assert result['reason'] == 'timeout'
        assert host.search(QUERY)['complete'] is True


def test_host_maintains_and_recovers_expired_readers(tmp_path):
    from ken.kql2.host import QueryHost
    import sqlite3
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        host.search(QUERY)
        with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
            db.execute('UPDATE k2_leases SET expires_ns=0')
        host.maintain()
        assert host.search(QUERY)['rows'] == [['Worker', 'a.py']]


def test_host_requires_its_owner_even_for_a_new_scope(tmp_path):
    from ken.kql2.host import QueryHost
    from concurrent.futures import ThreadPoolExecutor
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host, ThreadPoolExecutor(1) as worker:
        with pytest.raises(RuntimeError, match='thread'):
            worker.submit(host.search, QUERY).result()


def test_cli_and_mcp_use_shared_automatic_client(tmp_path, monkeypatch, capsys):
    from ken.cli import main
    from ken.kql2 import automatic
    from ken.mcp import server
    calls = []
    def prepared(root, source, **options):
        calls.append((root, source, options))
        return {'language':'kql/2','rows':[['Worker','a.py']], 'columns':['name','path'],
                'complete':True,'coverage_complete':True, 'unknown_candidates':0,
                'results_truncated':False, 'analysis':{'total_ms':1}}
    monkeypatch.setattr(automatic, 'search', prepared)
    monkeypatch.setattr(server, '_PROJECT_ROOT', tmp_path)
    query_file = tmp_path / 'query.kql'
    query_file.write_text(QUERY)
    assert main(['kql2', str(query_file), '--root', str(tmp_path)]) == 0
    capsys.readouterr()
    assert server.ken_find(query=QUERY, scope='structure', query_language='kql/2')['rows'] == [['Worker','a.py']]
    assert len(calls) == 2
    assert all(source == QUERY for _, source, _ in calls)


def test_new_cli_processes_reuse_service_and_return_updated_sources(tmp_path):
    import json
    import subprocess
    import sys
    from ken.kql2 import automatic
    file = tmp_path / 'a.py'
    file.write_text('class Worker: pass\n')
    query_file = tmp_path / 'query.kql'
    query_file.write_text(QUERY)
    command = [sys.executable, '-m', 'ken.kql2', str(query_file), '--root', str(tmp_path), '--json']
    try:
        first = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert first.returncode == 0, first.stderr
        one = json.loads(first.stdout)
        second = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert second.returncode == 0, second.stderr
        two = json.loads(second.stdout)
        assert one['rows'] == two['rows'] == [['Worker', 'a.py']]
        assert one['analysis']['session_pid'] == two['analysis']['session_pid']
        assert two['analysis']['parsed_units'] == 0
        assert two['analysis']['preparation_ms'] == 0
        before = file.stat()
        file.write_text('class Other: pass\n')
        os.utime(file, ns=(before.st_atime_ns, before.st_mtime_ns))
        third = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert third.returncode == 0, third.stderr
        assert json.loads(third.stdout)['rows'] == []
        assert not (tmp_path / '.ken/meta.json').exists()
    finally:
        automatic.shutdown(tmp_path)


def test_automatic_client_handles_mcp_threads_and_budget_reset(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from ken.kql2 import automatic
    from ken.mcp import server
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    monkeypatch.setattr(server, '_PROJECT_ROOT', tmp_path)
    try:
        def query():
            return server.ken_find(query=QUERY, scope='structure', query_language='kql/2', full=True)
        with ThreadPoolExecutor(3) as callers:
            results = list(callers.map(lambda _: query(), range(3)))
        assert all(r['rows'] == [['Worker', 'a.py']] and r['complete'] for r in results)
        assert len({r['analysis']['session_pid'] for r in results}) == 1
        assert automatic.search(tmp_path, QUERY, timeout_ms=0)['complete'] is False
        assert query()['complete'] is True
    finally:
        automatic.shutdown(tmp_path)


def test_restart_keeps_endpoint_replaced_by_another_client(tmp_path, monkeypatch):
    from ken.kql2 import automatic
    old = {'port':1234, 'token':'old', 'implementation':automatic.IMPLEMENTATION}
    fresh = {'port':5678, 'token':'fresh', 'implementation':automatic.IMPLEMENTATION}
    directory = automatic.runtime_path(tmp_path).parent
    directory.mkdir(parents=True)
    import json
    automatic.runtime_path(tmp_path).write_text(json.dumps(old))
    attempts = []
    def wire(endpoint, message, **options):
        attempts.append(endpoint['token'])
        if endpoint['token'] == 'old':
            automatic.runtime_path(tmp_path).write_text(json.dumps(fresh))
            raise ConnectionRefusedError
        return {'result':{'complete':True,'rows':[], 'analysis':{'total_ms':1, 'preparation_ms':0}}}
    monkeypatch.setattr(automatic, '_wire', wire)
    def no_spawn(*args, **kwargs):
        pytest.fail('a newer live endpoint was removed during restart')
    monkeypatch.setattr(automatic.subprocess, 'Popen', no_spawn)
    assert automatic.search(tmp_path, QUERY)['complete'] is True
    assert attempts == ['old', 'fresh']
    assert json.loads(automatic.runtime_path(tmp_path).read_text()) == fresh


def test_invalidation_at_final_freshness_check_cannot_deliver_old_success(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2.revision import RevisionMonitor
    file = tmp_path / 'a.py'
    file.write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        host.search(QUERY)
        original = RevisionMonitor.unchanged
        calls = [0]
        def changed(revision):
            current = original(revision)
            calls[0] += 1
            if calls[0] == 2:
                file.write_text('class Other: pass\n')
                host.resync()
            return current
        monkeypatch.setattr(RevisionMonitor, 'unchanged', changed)
        result = host.search(QUERY)
        assert result['complete'] is True
        assert result['rows'] == []


@pytest.mark.parametrize('failing', ['watcher', 'reader'])
def test_close_attempts_all_readers_and_can_retry_failed_cleanup(tmp_path, monkeypatch, failing):
    from ken.kql2.host import QueryHost
    for folder in ['one', 'two']:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'a.py').write_text('class Worker: pass\n')
    host = QueryHost(tmp_path, watch=False)
    host.search(QUERY, path='one')
    host.search(QUERY, path='two')
    sessions = [reader.session for reader in host._readers.values()]
    calls = []
    original = sessions[0].close
    def failed():
        calls.append('reader')
        if failing == 'reader' and calls.count('reader') == 1:
            raise RuntimeError('cleanup failed')
        original()
    monkeypatch.setattr(sessions[0], 'close', failed)
    class Watcher:
        def stop(self):
            calls.append('watcher')
            if calls.count('watcher') == 1:
                raise RuntimeError('cleanup failed')
    if failing == 'watcher':
        host._watcher = Watcher()
    with pytest.raises(RuntimeError, match='cleanup'):
        host.close()
    with pytest.raises(RuntimeError, match='closed'):
        sessions[1].search(QUERY)
    host.close()
    with pytest.raises(RuntimeError, match='closed'):
        sessions[0].search(QUERY)


def test_startup_retries_child_that_arrived_before_old_owner_released_lock(tmp_path, monkeypatch):
    import json
    from ken.kql2 import automatic
    old = {'port':1234, 'token':'old', 'implementation':'previous'}
    fresh = {'port':5678, 'token':'fresh', 'implementation':automatic.IMPLEMENTATION}
    runtime = automatic.runtime_path(tmp_path)
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps(old))
    starts = []
    class Child:
        def poll(self):
            return 0 if len(starts) == 1 else None
    def spawn(*args, **kwargs):
        starts.append('spawn')
        if len(starts) == 2:
            runtime.write_text(json.dumps(fresh))
        return Child()
    monkeypatch.setattr(automatic.subprocess, 'Popen', spawn)
    monkeypatch.setattr(automatic, '_wire', lambda *args, **kwargs: {'ok':True})
    monkeypatch.setattr(automatic, 'STARTUP_TIMEOUT_S', .1)
    endpoint, _ = automatic._ensure(tmp_path)
    assert endpoint == fresh
    assert len(starts) == 2


def test_invalid_root_or_scope_does_not_spawn_or_create_it(tmp_path, monkeypatch):
    from ken.kql2 import automatic
    root = tmp_path / 'missing'
    def no_spawn(*args, **kwargs):
        pytest.fail('invalid input attempted to start a query service')
    monkeypatch.setattr(automatic.subprocess, 'Popen', no_spawn)
    with pytest.raises(ValueError, match='exist'):
        automatic.search(root, QUERY)
    assert not root.exists()
    with pytest.raises(ValueError, match='escapes'):
        automatic.search(tmp_path, QUERY, path='../escape')
    assert not (tmp_path / '.ken').exists()


def test_explicit_unretained_budget_preserves_ephemeral_execution(tmp_path, monkeypatch):
    from ken.kql2 import automatic
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    monkeypatch.setattr(automatic, '_ensure', lambda *args: pytest.fail('ephemeral budget started a service'))
    result = automatic.search(tmp_path, QUERY, cache_mb=.1)
    assert result['complete'] is True
    assert result['rows'] == [['Worker', 'a.py']]
    assert result['analysis']['ephemeral'] is True


def test_failed_post_capture_still_closes_new_reader(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2.revision import SourceRevision
    import sqlite3
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    original = SourceRevision.capture
    calls = [0]
    def capture(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 2:
            raise ValueError('scope changed during preparation')
        return original(*args, **kwargs)
    monkeypatch.setattr(SourceRevision, 'capture', capture)
    with QueryHost(tmp_path, watch=False) as host:
        with pytest.raises(ValueError, match='scope changed'):
            host.search(QUERY)
    with sqlite3.connect(tmp_path / '.ken/structural/v2/store.sqlite') as db:
        assert db.execute('SELECT count(*) FROM k2_leases').fetchone()[0] == 0


def test_budget_does_not_include_preparation_queued_before_this_request(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from types import SimpleNamespace
    import ken.kql2.host as module
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    with QueryHost(tmp_path, watch=False) as host:
        host.search(QUERY)
        # The service prepared another request while this one was in its queue.
        host._preparations.append((10.0, 10.1))
        monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: 10.102))
        response = host.search(QUERY, timeout_ms=10, arrived_at=10.0)
        assert response['complete'] is True
        assert response['analysis']['index_wait_ms'] == pytest.approx(100)


def test_retention_fallback_survives_connection_restart(tmp_path, monkeypatch):
    from ken.kql2 import automatic
    from ken.kql2.session import PersistentStorageRequired
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    attempts = []
    monkeypatch.setattr(automatic, '_ensure', lambda *args, **kwargs: ({'token':'owner'}, 0))
    def wire(*args, **kwargs):
        attempts.append('query')
        if len(attempts) == 1:
            raise ConnectionError('owner died')
        raise PersistentStorageRequired('source capture exceeds retention')
    monkeypatch.setattr(automatic, '_wire', wire)
    result = automatic.search(tmp_path, QUERY, cache_mb=1)
    assert result['complete'] is True
    assert result['rows'] == [['Worker', 'a.py']]
    assert len(attempts) == 2


def test_lru_keeps_failed_cleanup_owned_for_host_close(tmp_path, monkeypatch):
    import ken.kql2.host as module
    monkeypatch.setattr(module, 'MAX_SESSIONS', 1)
    for folder in ['one', 'two']:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'a.py').write_text('class Worker: pass\n')
    host = module.QueryHost(tmp_path, watch=False)
    host.search(QUERY, path='one')
    reader = next(iter(host._readers.values())).session
    original = reader.close
    attempts = []
    def close():
        attempts.append('close')
        if len(attempts) == 1:
            raise RuntimeError('cleanup failed')
        original()
    monkeypatch.setattr(reader, 'close', close)
    try:
        with pytest.raises(RuntimeError, match='cleanup'):
            host.search(QUERY, path='two')
    finally:
        host.close()
    assert len(attempts) == 2
    with pytest.raises(RuntimeError, match='closed'):
        reader.search(QUERY)


def test_failed_eviction_cannot_reuse_a_closed_reader(tmp_path, monkeypatch):
    import ken.kql2.host as module
    monkeypatch.setattr(module, 'MAX_SESSIONS', 1)
    for folder in ['one', 'two']:
        (tmp_path / folder).mkdir()
        (tmp_path / folder / 'a.py').write_text('class Worker: pass\n')
    with module.QueryHost(tmp_path, watch=False) as host:
        host.search(QUERY, path='one')
        reader = next(iter(host._readers.values())).session
        original = reader.close
        calls = []
        def close():
            original()
            calls.append('close')
            if len(calls) == 1:
                raise RuntimeError('lease cleanup failed after connection closed')
        monkeypatch.setattr(reader, 'close', close)
        with pytest.raises(RuntimeError, match='cleanup'):
            host.search(QUERY, path='two')
        result = host.search(QUERY, path='one')
        assert result['complete'] is True
        assert result['rows'] == [['Worker', 'one/a.py']]


def test_timeout_does_not_restart_or_replay_live_request(tmp_path, monkeypatch):
    from ken.kql2 import automatic
    attempts = []
    def ensure(*args, **kwargs):
        attempts.append('ensure')
        return {'token':'owner'}, 0
    def wire(*args, **kwargs):
        attempts.append('query')
        raise TimeoutError('live request still running')
    monkeypatch.setattr(automatic, '_ensure', ensure)
    monkeypatch.setattr(automatic, '_wire', wire)
    with pytest.raises(TimeoutError):
        automatic.search(tmp_path, QUERY)
    assert attempts == ['ensure', 'query']


def test_cli_recovers_dead_owner_and_rpc_rejects_bad_requests(tmp_path):
    import signal
    from ken.kql2 import automatic
    (tmp_path / 'a.py').write_text('class Worker: pass\n')
    try:
        first = automatic.search(tmp_path, QUERY)
        endpoint = automatic._endpoint(tmp_path)
        assert endpoint is not None
        with pytest.raises(ValueError, match='unauthorised'):
            automatic._wire({**endpoint, 'token':'wrong'}, {'action':'shutdown'})
        with pytest.raises(ValueError, match='unknown'):
            automatic._wire(endpoint, {'action':'invalid'})
        assert automatic.search(tmp_path, QUERY)['rows'] == first['rows']
        os.kill(first['analysis']['session_pid'], signal.SIGTERM)
        (tmp_path / 'a.py').write_text('class Other: pass\n')
        result = automatic.search(tmp_path, QUERY)
        assert result['complete'] is True
        assert result['rows'] == []
        assert result['analysis']['session_pid'] != first['analysis']['session_pid']
    finally:
        automatic.shutdown(tmp_path)


def test_failed_retirement_blocks_further_pool_growth(tmp_path, monkeypatch):
    import ken.kql2.host as module
    monkeypatch.setattr(module, 'MAX_SESSIONS', 1)
    for name in ['one', 'two', 'three']:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'a.py').write_text('class Worker: pass\n')
    host = module.QueryHost(tmp_path, watch=False)
    host.search(QUERY, path='one')
    reader = next(iter(host._readers.values())).session
    original = reader.close
    def failed():
        raise RuntimeError('cleanup failed')
    monkeypatch.setattr(reader, 'close', failed)
    try:
        for scope in ['two', 'three']:
            with pytest.raises(RuntimeError, match='cleanup'):
                host.search(QUERY, path=scope)
        assert len(host._readers) + len(host._retiring) == 1
    finally:
        monkeypatch.setattr(reader, 'close', original)
        host.close()


def test_fallback_total_includes_failed_service_preparation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ken.kql2 import automatic, service
    from ken.kql2.session import PersistentStorageRequired
    now = [10.0]
    monkeypatch.setattr(automatic, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    def ensure(*args, **kwargs):
        now[0] += .100
        return {'token':'owner'}, 100
    def wire(*args, **kwargs):
        now[0] += .200
        raise PersistentStorageRequired('cannot retain sources')
    def fallback(*args, **kwargs):
        now[0] += .050
        return {'complete':True, 'analysis':{'total_ms':50}}
    monkeypatch.setattr(automatic, '_ensure', ensure)
    monkeypatch.setattr(automatic, '_wire', wire)
    monkeypatch.setattr(service, 'search', fallback)
    result = automatic.search(tmp_path, QUERY)
    assert result['analysis']['total_ms'] == pytest.approx(350)
    assert result['analysis']['startup_ms'] == pytest.approx(100)
    assert result['analysis']['session_attempt_ms'] == pytest.approx(200)
