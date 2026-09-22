"""``where receives($parameter, $type);`` — the value a call site hands a parameter.

The legacy catalogue stated this with ``CALL_BINDING``/``BINDING_PARAMETER``/
``BINDING_VALUE`` joined to ``TYPE`` or ``ALLOCATES_TYPE``: the untyped Memento
restore parameter is correlated with the snapshot only because an observed caller
passes one.  This is the KQL 2 spelling of the same claim.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(predicate: str = 'receives($memento, $snapshot)') -> str:
    return ('language "kql/2"; module t; '
            'pattern detect(out Callable $restore) { '
            'type $snapshot { field $saved {} '
            'method $getter { arity: 0; body { return $saved; } } } '
            'type $originator { field $state {} } '
            'callable $restore { name: "restore"; param $memento {} '
            'writes: exactly($state, 1); } '
            f'where {predicate}; '
            '} '
            'query results { use detect(restore: $restore); select $restore; }')


def write(tmp_path, tail: str) -> None:
    (tmp_path / 'a.py').write_text(
        'class Snapshot:\n'
        '    def __init__(self, state):\n'
        '        self.saved = state\n'
        '    def get(self):\n'
        '        return self.saved\n'
        'class Other:\n'
        '    def get(self):\n'
        '        return 0\n'
        'class Originator:\n'
        '    def restore(self, s):\n'
        '        self.state = s.get()\n'
        + tail)


def test_a_construction_passed_for_the_parameter_is_the_type(tmp_path):
    write(tmp_path, 'origin = Originator()\norigin.restore(Snapshot(1))\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_a_typed_local_passed_for_the_parameter_is_the_type(tmp_path):
    write(tmp_path, 'snap = Snapshot(1)\norigin = Originator()\norigin.restore(snap)\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_a_parameter_no_call_site_fills_is_rejected(tmp_path):
    write(tmp_path, 'origin = Originator()\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_another_type_passed_for_the_parameter_is_rejected(tmp_path):
    write(tmp_path, 'origin = Originator()\norigin.restore(Other())\n')
    result = search(tmp_path, query(), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_a_three_argument_form_is_rejected(tmp_path):
    write(tmp_path, 'origin = Originator()\norigin.restore(Snapshot(1))\n')
    with pytest.raises(Exception):
        search(tmp_path, query('receives($memento, $snapshot, $extra)'), cache_mb=0)


def test_the_two_roles_are_not_interchangeable(tmp_path):
    write(tmp_path, 'origin = Originator()\norigin.restore(Snapshot(1))\n')
    result = search(tmp_path, query('receives($snapshot, $memento)'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result
