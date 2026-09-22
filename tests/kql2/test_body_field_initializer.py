"""``initializer { $field = $param; }`` — a constructor storing a parameter into a field.

The legacy catalogue stated instance-state retention with ``CONSTRUCTOR_FIELD_INPUT``
together with ``HAS_METHOD``/``HAS_PARAMETER`` on the constructor.  The KQL 2 spelling
of the same claim is the constructor body's declaration phase: an ``initializer`` step
that is the first step of the body and whose assignments go from the constructor's
parameters to the fields that retain them.

This is what ``command.retained-contract`` and ``bridge.#constructor`` need, so the
spelling is pinned here before the catalogue entries move to it.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(initializer: str = '$state = $input;', select: str = '$unit') -> str:
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $state { name: "state"; } method $ctor { '
            'constructor: true; param $input { name: "state"; } body { '
            f'initializer {{ {initializer} }} '
            f'}} }} }} select {select}; }}')


def write(tmp_path, body: str) -> None:
    (tmp_path / 'a.py').write_text(
        'class Holder:\n'
        f'    def __init__(self, state):\n        {body}\n')


def test_initializer_matches_a_parameter_stored_into_a_field(tmp_path):
    write(tmp_path, 'self.state = state')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_initializer_captures_the_input_parameter(tmp_path):
    write(tmp_path, 'self.state = state')
    result = search(tmp_path, query(select='$unit, $state, $input'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result
    assert 'PARAMETER:state' in str(result['rows'][0]), result['columns']


def test_initializer_rejects_a_constant(tmp_path):
    # A constant is assigned, not a parameter: nothing is retained from the input.
    write(tmp_path, 'self.state = 0')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_initializer_rejects_another_field(tmp_path):
    write(tmp_path, 'self.other = state')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_initializer_must_name_the_constructor_param(tmp_path):
    # ``$missing`` is not a parameter of the constructor, so the assignment is not
    # the input this clause claims.
    write(tmp_path, 'self.state = state')
    with pytest.raises(Exception):
        search(tmp_path, query('$state = $missing;'), cache_mb=0)


def test_initializer_must_be_the_first_body_step(tmp_path):
    write(tmp_path, 'self.state = state')
    source = ('language "kql/2"; module t; query q { '
              'type $unit { field $state { name: "state"; } method $ctor { '
              'constructor: true; param $input { name: "state"; } body { '
              'let $ignored = call $other { } as $op; '
              'initializer { $state = $input; } '
              '} } } select $unit; }')
    with pytest.raises(Exception):
        search(tmp_path, source, cache_mb=0)
