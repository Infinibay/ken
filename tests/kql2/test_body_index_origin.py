"""``argument $container[$key] at any;`` — an operand that is an element of a container.

The legacy catalogue stated element origin with the ``VALUE``/``INDEX``/``CONTAINER``
chain.  This is the KQL 2 spelling of the same claim: the argument of the call is an
element of a place the pattern bound, optionally at a key the pattern also bound.  The
transformation of an incoming request into two call arguments (the functional adapter)
is the shape that needs it.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(argument: str, target: str = 'sink') -> str:
    return ('language "kql/2"; module t; query q { '
            f'callable ${target} {{ name: "{target}"; }} '
            'callable $f { name: "forward"; param $request { name: "request"; } '
            'param $topic { name: "topic"; } body { '
            f'call ${target} {{ {argument} }}; '
            '} } select $f; }')


def write(tmp_path, body: str = 'sink(request[0], request[1])') -> None:
    (tmp_path / 'a.py').write_text(
        'def sink(a, b=None):\n'
        '    return a\n'
        'def forward(request, topic):\n'
        f'    {body}\n'
        '    return request\n')


def test_indexed_argument_matches_the_element_of_the_bound_container(tmp_path):
    write(tmp_path)
    result = search(tmp_path, query('argument $request[_] at any;'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_argument_rejects_an_unrelated_container(tmp_path):
    # The element that reaches ``sink`` comes from ``topic``, never from ``request``:
    # the container role is a name for one place, not a wildcard over every index.
    write(tmp_path, 'sink(topic[0], topic[1])')
    result = search(tmp_path, query('argument $request[_] at any;'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_indexed_argument_captures_an_unbound_key_role(tmp_path):
    # ``$slot`` is not a place the pattern bound, so it is the key this access
    # uses: the element origin is the claim, and the key is captured with it.
    write(tmp_path, 'sink(request["a"])')
    result = search(tmp_path, query('argument $request[$slot] at any;'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_argument_key_correlates_a_bound_key(tmp_path):
    write(tmp_path, 'sink(request[topic])')
    matched = query('argument $request[$topic] at any;')
    assert len(search(tmp_path, matched, cache_mb=0)['rows']) == 1
    # A different key selects a different element, so it is not this access.
    other = query('argument $request[$request] at any;')
    assert search(tmp_path, other, cache_mb=0)['rows'] == []


def test_index_requires_a_bound_container(tmp_path):
    write(tmp_path)
    # ``$missing`` is never declared: the container of an element origin must be a
    # place the pattern bound, otherwise the spelling is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query('argument $missing[_] at any;'), cache_mb=0)
