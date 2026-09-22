"""``let $key = call $derive { ... } writes: 1;`` — the place the call's result filled.

An interning method derives its key from a parameter, then indexes the pool by that
local. The legacy catalogue said so with ``ASSIGNED_FROM(place, call)`` beside
``STORAGE_WRITE_COUNT(place, "1")``: the *place* is the correlation, not the call result
value, so the same role can index the store and the return. Stating ``writes: n`` on the
capture is the pattern saying which place it means, and the inventory must agree.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

ONE_WRITE = '''class Product:
    def __init__(self, state): self.state = state
class Pool:
    def __init__(self): self.pool = {}
    def key_for(self, state): return str(state)
    def get(self, state):
        key = self.key_for(state)
        self.pool[key] = Product(state)
        return self.pool[key]
'''

TWO_WRITES = ONE_WRITE.replace('        key = self.key_for(state)',
                               '        key = self.key_for(state)\n        key = "fixed"')

OTHER_INDEX = ONE_WRITE.replace('        return self.pool[key]',
                                '        self.pool["fixed"] = Product(state)\n'
                                '        return self.pool["fixed"]')


def query(capture: str, role: str = 'key') -> str:
    return ('language "kql/2";\nmodule t;\n'
            'pattern detect(out TypeDecl $unit, out Callable $get, out Field $pool,'
            ' out Parameter $state) {\n'
            '  type $unit {\n'
            '    field $pool {}\n'
            '    method $get {\n'
            '      constructor: false;\n'
            '      parameters { param $state {} }\n'
            '      body {\n'
            '        ' + capture + '\n'
            '        let $filled = construct $product { argument $state at 0; };\n'
            '        $pool[$' + role + '] = $filled as $write;\n'
            '        return $pool[$' + role + '];\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
            'query results {\n'
            '  use detect(unit: $unit, get: $get, pool: $pool, state: $state);\n'
            '  select $unit;\n'
            '}\n')


def matches(tmp_path, source: str, capture: str, role: str = 'key') -> bool:
    (tmp_path / 'pool.py').write_text(source)
    result = search(tmp_path, query(capture, role), cache_mb=0)
    assert result['complete'], result
    return len(result['rows']) == 1


CAPTURE = 'let $key = call $derive { argument $state at 0; } writes: 1;'


def test_call_capture_binds_the_place_the_result_filled(tmp_path):
    assert matches(tmp_path, ONE_WRITE, CAPTURE)


def test_call_capture_rejects_a_place_with_another_write(tmp_path):
    assert not matches(tmp_path, TWO_WRITES, CAPTURE)


def test_stated_count_must_agree_with_the_inventory(tmp_path):
    assert not matches(tmp_path, ONE_WRITE,
                       'let $key = call $derive { argument $state at 0; } writes: 2;')


def test_call_capture_still_correlates_the_place_with_the_index(tmp_path):
    assert not matches(tmp_path, OTHER_INDEX, CAPTURE)


def test_capture_role_name_is_free(tmp_path):
    renamed = ONE_WRITE.replace('key', 'derived')
    assert matches(tmp_path, renamed,
                   'let $slot = call $derive { argument $state at 0; } writes: 1;', 'slot')
