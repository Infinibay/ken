"""``call $table[$key] { ... }`` — the invoked value is an element of a bound container.

The legacy catalogue stated a keyed dispatch with the ``CALLEE_VALUE``/``CONTAINER``/
``INDEX`` chain: the value that reaches the call is the element a key selects out of a
table the pattern also bound.  This is the KQL 2 spelling of the same claim, the callee
counterpart of ``argument $container[$key]``.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(callee: str) -> str:
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $table { name: "table"; } method $dispatch { '
            'param $requested { name: "requested"; } body { '
            f'call {callee} {{ }} as $call; '
            '} } } select $unit; }')


PYTHON = ('class Registry:\n'
          ' def register(self, key, handler):\n'
          '  self.table[key] = handler\n'
          '  self.other[key] = handler\n'
          ' def dispatch(self, requested, data): return self.table[requested](data)\n')


def write(tmp_path, body: str) -> None:
    (tmp_path / 'a.py').write_text(
        'class Registry:\n'
        ' def register(self, key, handler):\n'
        '  self.table[key] = handler\n'
        '  self.other[key] = handler\n'
        f' def dispatch(self, requested, data): {body}\n')


def test_element_callee_matches_the_keyed_dispatch(tmp_path):
    write(tmp_path, 'return self.table[requested](data)')
    result = search(tmp_path, query('$table[$requested]'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_element_callee_rejects_an_unrelated_container(tmp_path):
    # The invoked value comes out of ``other``, never out of the bound ``table``:
    # the container role names one place, not any field of the type.
    write(tmp_path, 'return self.other[requested](data)')
    result = search(tmp_path, query('$table[$requested]'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_element_callee_key_correlates(tmp_path):
    write(tmp_path, 'return self.table[requested](data)')
    assert len(search(tmp_path, query('$table[$requested]'), cache_mb=0)['rows']) == 1
    # A different key selects a different element, so it is not this call.
    write(tmp_path, 'return self.table[data](requested)')
    assert search(tmp_path, query('$table[$requested]'), cache_mb=0)['rows'] == []


def test_element_callee_wildcard_key_accepts_any_element(tmp_path):
    write(tmp_path, 'return self.table[requested](data)')
    result = search(tmp_path, query('$table[_]'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_element_callee_requires_a_bound_container(tmp_path):
    write(tmp_path, 'return self.table[requested](data)')
    # ``$missing`` is never declared: the container of an element origin must be a
    # place the pattern bound, otherwise the spelling is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query('$missing[$requested]'), cache_mb=0)


def test_element_callee_is_not_a_plain_element_read(tmp_path):
    # ``self.table[requested]`` read into a local is not the invoked value.
    write(tmp_path, 'entry = self.table[requested]\n  return entry(data)')
    result = search(tmp_path, query('$table[$requested]'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


GO = ('package p; type Registry struct { table map[string]func(int)int }; '
      'func(r *Registry) register(key string, handler func(int)int) { r.table[key] = handler }; '
      'func(r *Registry) dispatch(requested string, data int) int { return r.table[requested](data) }')


def test_element_callee_matches_a_go_keyed_dispatch(tmp_path):
    # Go's grammar parses the indexed call as a type conversion, so the operation is
    # not filed as a call; the semantic layer still publishes the call occurrence.
    # The saved-rule executor is the path that evaluates catalogue rules, so the case
    # is stated there.
    from ken.structural.frontend import lower_source
    from ken.structural.rules import SavedRule, builtin_rules, execute_rules
    from ken.structural.semantic import link_project
    source = ('language "kql/2"; module t;\n'
              'pattern detect(out TypeDecl $unit, out Field $table, out Callable $dispatch) {\n'
              '  type $unit { field $table { name: "table"; } method $dispatch { '
              'param $requested { name: "requested"; } body { call $table[$requested] { } as $call; } } }\n'
              '}\n'
              'query results { use detect(unit: $unit, table: $table, dispatch: $dispatch); '
              'select $unit; }\n')
    graph = link_project([lower_source(GO, 'go', 'a.go')])
    rule = SavedRule(id='t', name='t', query=source, source=source, query_language='kql/2')
    result = execute_rules(graph, [rule], registry=builtin_rules())
    assert result['complete'] and len(result['matches']) == 1, result['outcomes']
