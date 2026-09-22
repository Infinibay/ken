"""``argument from $place`` / ``return from $place`` -- an operand derived from a place.

The legacy catalogue stated a *computed* origin with a dependence chain: the argument of a
delegated call is a value that consumes the method's parameter (the object adapter's input
conversion), and the value a method returns is a value that consumes the delegated call
(its output conversion).  The KQL 2 spelling of that claim is the ``from`` suffix: the
operand itself stays unnamed, and the pattern names the place the derivation starts at.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(instruction: str, target: str = 'sink') -> str:
    return ('language "kql/2"; module t; query q { '
            f'callable ${target} {{ name: "{target}"; }} '
            'callable $f { name: "forward"; param $request { name: "request"; } '
            'param $topic { name: "topic"; } body { '
            f'{instruction} '
            '} } select $f; }')


def write(tmp_path, body: str) -> None:
    (tmp_path / 'a.py').write_text(
        'def sink(a):\n'
        '    return a\n'
        'def forward(request, topic):\n'
        f'{body}\n')


ARGUMENT = 'call $sink { argument from $request at any; };'


def test_derived_argument_matches_a_computation_over_the_bound_parameter(tmp_path):
    write(tmp_path, '    sink(request * 2)')
    result = search(tmp_path, query(ARGUMENT), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_derived_argument_accepts_a_call_result_over_the_parameter(tmp_path):
    write(tmp_path, '    sink(str(request))')
    result = search(tmp_path, query(ARGUMENT), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_derived_argument_rejects_an_unrelated_place(tmp_path):
    # The operand consumes ``topic`` and never ``request``: the place in the clause is a
    # name for one derivation, not a wildcard over every argument.
    write(tmp_path, '    sink(topic)')
    result = search(tmp_path, query(ARGUMENT), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_derived_argument_rejects_a_constant(tmp_path):
    write(tmp_path, '    sink(1)')
    result = search(tmp_path, query(ARGUMENT), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


RETURNED = 'call $sink { } as $local_call; return from $sink;'


def test_derived_return_matches_a_result_the_call_result_feeds(tmp_path):
    write(tmp_path, '    result = sink(request)\n    return result + 1')
    result = search(tmp_path, query(RETURNED), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_derived_return_rejects_a_place_the_call_never_fed(tmp_path):
    write(tmp_path, '    sink(request)\n    return topic')
    result = search(tmp_path, query(RETURNED), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_derivation_requires_a_bound_place(tmp_path):
    write(tmp_path, '    sink(request)')
    # ``$missing`` is never declared: the derivation starts at a place the pattern bound,
    # otherwise the spelling is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query('call $sink { argument from $missing at any; };'), cache_mb=0)
