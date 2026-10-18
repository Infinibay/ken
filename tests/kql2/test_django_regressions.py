"""Source relationships and preparation costs exposed by the pinned Django trial."""

from textwrap import dedent

import pytest

from ken.kql2.service import search
from ken.kql2.session import QuerySession


RETURNED = '''language "kql/2"; module regression.values; query returned {
  callable $owner { body {
    let $value = call $site { name: "mark_safe"; };
    return $value;
  } }
  select $owner;
}'''


def test_prepared_hazards_do_not_build_an_unused_project_graph(tmp_path, monkeypatch):
    from ken.kql2 import graph_execution

    (tmp_path / 'sample.py').write_text('def bad(items=[]): return items\n')
    query = '''language "kql/2"; module regression.hazards; query hazards {
      edge HAS_HAZARD($site, "mutable-default-argument"); select $site;
    }'''
    with QuerySession(tmp_path) as session:
        def forbidden(*args, **kwargs):
            pytest.fail('a hazard-only query must not prepare a project graph')

        monkeypatch.setattr(graph_execution, 'graph_index', forbidden)
        session.prepare_query(query)
        result = session.search(query)
    assert result['complete'] and result['coverage_complete']
    assert result['unknown_candidates'] == 0
    assert len(result['rows']) == 1
    assert 'mutable-default-argument' in result['rows'][0][0]


def test_semantics_that_cannot_fit_skip_the_failed_shared_write(tmp_path):
    (tmp_path / 'sample.py').write_text(
        'def mark_safe(value): return value\n'
        'def forwarded(value): return mark_safe(value)\n'
    )
    with QuerySession(tmp_path) as session:
        store = session._store
        store.limit_bytes = store.allocated_bytes + 1
        statements = []
        store.db.set_trace_callback(statements.append)
        session.prepare_query(RETURNED)
        assert session._semantic_index.storage == 'session_disk'
        assert not any(sql.startswith('INSERT INTO k2_semantic_terms') for sql in statements)
        assert session.search(RETURNED)['rows'][0][0]['name'] == 'forwarded'


def test_unrelated_parse_errors_do_not_erase_a_known_return_witness(tmp_path):
    (tmp_path / 'sample.py').write_text(
        'def mark_safe(value): return value\n'
        'def forwarded(value): return mark_safe(value)\n'
    )
    (tmp_path / 'unrelated.py').write_text('def broken(\n')
    result = search(tmp_path, RETURNED, cache_mb=0)
    assert [row[0]['name'] for row in result['rows']] == ['forwarded']
    assert result['complete']
    assert not result['coverage_complete']


def test_lambda_returns_the_value_of_its_body_call(tmp_path):
    (tmp_path / 'sample.py').write_text(
        'def mark_safe(value): return value\n'
        '\nforwarded = lambda value: mark_safe(value)\n'
    )
    result = search(tmp_path, RETURNED, cache_mb=0)
    assert [row[0]['line'] for row in result['rows']] == [3]
    assert result['complete'] and result['coverage_complete']
    assert result['unknown_candidates'] == 0


def test_returned_call_in_try_has_a_normal_path_witness(tmp_path):
    (tmp_path / 'sample.py').write_text(dedent('''\
        def mark_safe(value): return value
        def forwarded(value):
            try:
                return mark_safe(value)
            except ValueError:
                raise
    '''))
    result = search(tmp_path, RETURNED, cache_mb=0)
    assert [row[0]['name'] for row in result['rows']] == ['forwarded']
    assert result['complete'] and result['coverage_complete']


def test_finally_overriding_return_never_produces_a_false_witness(tmp_path):
    (tmp_path / 'sample.py').write_text(dedent('''\
        def mark_safe(value): return value
        def replaced(value):
            try:
                return mark_safe(value)
            finally:
                return None
    '''))
    result = search(tmp_path, RETURNED, cache_mb=0)
    assert result['rows'] == []
    assert result['complete']


def test_declarations_do_not_materialize_an_unused_canonical_ast(tmp_path, monkeypatch):
    import ken.common_ast

    (tmp_path / 'sample.py').write_text('class Worker: pass\n')
    with monkeypatch.context() as patch:
        def forbidden(*args, **kwargs):
            pytest.fail('declaration inventory must not project the canonical AST')

        patch.setattr(ken.common_ast, 'normalize', forbidden)
        result = search(tmp_path, '''language "kql/2"; module regression.declarations;
          query owners { class $owner {} select $owner.name; }
        ''')
    assert result['rows'] == [['Worker']]
    # A later syntax query still acquires the complete canonical representation.
    syntax = search(tmp_path, '''language "kql/2"; module regression.syntax;
      query declarations { node $node {native_kind: "class_definition";} select $node; }
    ''')
    assert len(syntax['rows']) == 1 and syntax['complete']


def test_closed_call_inventory_excludes_unrelated_partial_bodies(tmp_path):
    (tmp_path / 'sample.py').write_text(dedent('''\
        def mark_safe(value): return value
        def forwarded(value): return mark_safe(value)
        def unrelated():
            yield object()
    '''))
    result = search(tmp_path, RETURNED, cache_mb=0)
    assert [row[0]['name'] for row in result['rows']] == ['forwarded']
    assert result['unknown_candidates'] == 0


def test_bound_exact_call_target_prunes_unrelated_partial_bodies_but_keeps_aliases(tmp_path):
    (tmp_path / 'helper.py').write_text('def target(): return 1\n')
    (tmp_path / 'sample.py').write_text(dedent('''\
        from helper import target as alias
        def alias_call():
            return alias()
        def unrelated():
            yield object()
    '''))
    query = '''language "kql/2"; module regression.target_candidates;
      query q {callable $target {name:"target";}
        callable $owner {body {call $target {};}} select $owner.name;}'''
    result = search(tmp_path, query, cache_mb=0)
    assert result['rows'] == [['alias_call']]
    assert result['unknown_candidates'] == 0


def test_automatic_hazards_select_specialized_acquisition(tmp_path, monkeypatch):
    from ken.kql2 import graph_execution, service
    from ken.kql2.host import QueryHost

    (tmp_path / 'sample.py').write_text('def bad(items=[]): return items\n')
    def forbidden(*args, **kwargs):
        pytest.fail('a local hazard must not start full source preparation')

    with QueryHost(tmp_path, watch=False) as host:
        with monkeypatch.context() as patch:
            patch.setattr(service, 'lower_source', forbidden)
            patch.setattr(graph_execution, 'graph_index', forbidden)
            result = host.search('''language "kql/2"; module regression.local;
              query hazards {edge HAS_HAZARD($site, "mutable-default-argument"); select $site;}
            ''')
        declarations = host.search('''language "kql/2"; module regression.full;
          query declarations {callable $f {} select $f.name;}''')
        assert declarations['rows'] == [['bad']]
        assert declarations['analysis']['source_profile'] == 'full'
    assert len(result['rows']) == 1
    assert result['analysis']['source_profile'] == 'local_hazards'
    assert result['analysis']['result_cache'] == 'disabled'


def test_disconnected_client_stops_acquisition_and_owner_can_serve_again(tmp_path, monkeypatch):
    import socket
    from ken.kql2 import request, service, worker
    from ken.kql2.host import QueryHost

    for name in ['One', 'Two']:
        (tmp_path / (name + '.py')).write_text('class ' + name + ': pass\n')
    client, connection = socket.socketpair()
    lower = service.lower_source
    def disconnect_after_source(*args, **kwargs):
        value = lower(*args, **kwargs)
        client.close()
        return value

    query = '''language "kql/2"; module regression.cancel;
      query owners {class $c {} select $c.name;}'''
    try:
        with QueryHost(tmp_path, watch=False) as host:
            with monkeypatch.context() as patch:
                patch.setattr(service, 'lower_source', disconnect_after_source)
                with request.cancellable(lambda: worker.client_disconnected(connection)):
                    with pytest.raises(request.RequestCancelled):
                        host.search(query)
            result = host.search(query)
            assert result['rows'] == [['One'], ['Two']]
            assert result['complete'] and result['coverage_complete']
    finally:
        client.close()
        connection.close()


def test_specialized_reader_refuses_full_preparation(tmp_path):
    (tmp_path / 'sample.py').write_text('def bad(items=[]): return items\n')
    with QuerySession(tmp_path, source_profile='local_hazards') as session:
        with pytest.raises(ValueError, match='full-source'):
            session.prepare_query(RETURNED)


def test_cancelled_refresh_does_not_restart_during_idle_maintenance(tmp_path, monkeypatch):
    from ken.kql2 import request, service
    from ken.kql2.host import QueryHost

    source = tmp_path / 'sample.py'
    source.write_text('class Before: pass\n')
    query = '''language "kql/2"; module regression.cancel_refresh;
      query q {class $c {} select $c.name;}'''
    with QueryHost(tmp_path, watch=False) as host:
        assert host.search(query)['rows'] == [['Before']]
        source.write_text('class After: pass\n')
        (tmp_path / 'other.py').write_text('class Other: pass\n')
        host.resync()
        lower = service.lower_source
        calls = []
        def track(*args, **kwargs):
            calls.append(True)
            return lower(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(service, 'lower_source', track)
            with request.cancellable(lambda: bool(calls)):
                with pytest.raises(request.RequestCancelled):
                    host.search(query)
            calls.clear()
            host.maintain()
            assert calls == []
        assert host.search(query)['rows'] == [['After'], ['Other']]


def test_registry_change_during_acquisition_reselects_source_profile(tmp_path, monkeypatch):
    from ken.kql2.host import QueryHost
    from ken.kql2.registry import ModuleRegistry

    (tmp_path / 'sample.py').write_text('def bad(items=[]): return items\n')
    hazard = '''language "kql/2"; module regression.changing;
      query q {edge HAS_HAZARD($site,"mutable-default-argument"); select $site;}'''
    full = '''language "kql/2"; module regression.changing;
      query q {callable $f {} select $f.name;}'''
    registry = ModuleRegistry(tmp_path)
    initial = registry.save(hazard)
    with QueryHost(tmp_path, watch=False) as host:
        ready = host._ready
        changed = False
        def change_after_acquisition(key):
            nonlocal changed
            value = ready(key)
            if not changed:
                registry.save(full, expected_revision=initial.revision)
                changed = True
            return value
        monkeypatch.setattr(host, '_ready', change_after_acquisition)
        result = host.search(saved_query='regression.changing')
    assert result['rows'] == [['bad']]
    assert result['analysis']['source_profile'] == 'full'
