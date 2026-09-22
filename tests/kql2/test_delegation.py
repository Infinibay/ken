"""Delegation primitives: what a method calls *on* a place, and *which* slot it forwards.

``delegates_to`` answers "does this callable invoke something on this place" and
``forwards_slot`` answers "is the invoked operation the one the callable overrides,
by name". Both are reachability-gated: a call in dead code forwards nothing. The
``call`` selector binds call occurrences owned by a callable, which is how a pattern
requires work *besides* the delegation.
"""
from __future__ import annotations

from ken.kql2.service import search


def query(body: str) -> str:
    return f'language "kql/2"; module t; query q {{ {body} }}'


def test_delegates_to_binds_the_place_a_method_invokes_on(tmp_path):
    (tmp_path / 'a.py').write_text(
        'class Contract:\n def run(self): return 0\n'
        'class Subject(Contract):\n'
        ' def __init__(self, inner: Contract): self.inner = inner\n'
        ' def run(self):\n  trace()\n  return self.inner.run()\n')
    result = search(tmp_path, query(
        'type $unit { field $place { } method $method { } } '
        'where delegates_to($method, $place); select $method.name, $place.name;'), cache_mb=0)
    assert result['complete'] and result['rows'] == [['run', 'inner']]


def test_forwards_slot_requires_the_delegated_name_to_match_the_overridden_slot(tmp_path):
    source = ('class Contract:\n def run(self): return 0\n'
              'class Subject(Contract):\n'
              ' def __init__(self, inner: Contract): self.inner = inner\n'
              ' def run(self):\n  trace()\n  return self.inner.{callee}()\n')
    overridden = query(
        'type $contract { method $slot { } } type $unit { method $method { } } '
        'where forwards_slot($method, $slot); select $method.name, $slot.name;')
    delegated = query(
        'type $unit { field $place { } method $method { } } '
        'where delegates_to($method, $place); select $method.name, $place.name;')
    (tmp_path / 'a.py').write_text(source.format(callee='run'))
    assert search(tmp_path, overridden, cache_mb=0)['rows'] == [['run', 'run']]
    (tmp_path / 'a.py').write_text(source.format(callee='other'))
    # The same delegation, spelled like another operation: the place still receives a
    # call, but the overridden slot is not the operation being forwarded.
    assert search(tmp_path, delegated, cache_mb=0)['rows'] == [['run', 'inner']]
    assert search(tmp_path, overridden, cache_mb=0)['rows'] == []


def test_call_selector_binds_owned_calls_and_excludes_dead_code(tmp_path):
    (tmp_path / 'a.py').write_text(
        'class C:\n def live(self):\n  trace()\n  return 1\n'
        ' def dead(self):\n  return 1\n  other()\n')
    owned = query('callable $method { call $call { } } select $method.name, $call.name;')
    reachable = query('callable $method { call $call { execution: "possible"; } } '
                      'select $method.name, $call.name;')
    assert sorted(search(tmp_path, owned, cache_mb=0)['rows']) == [['dead', 'other'], ['live', 'trace']]
    assert search(tmp_path, reachable, cache_mb=0)['rows'] == [['live', 'trace']]


def test_a_delegation_in_dead_code_does_not_satisfy_the_predicate(tmp_path):
    (tmp_path / 'a.py').write_text(
        'class Contract:\n def run(self): return 0\n'
        'class Subject(Contract):\n'
        ' def __init__(self, inner: Contract): self.inner = inner\n'
        ' def run(self):\n  return 1\n  return self.inner.run()\n')
    result = search(tmp_path, query(
        'type $unit { field $place { } method $method { } } '
        'where delegates_to($method, $place); select $method.name, $place.name;'), cache_mb=0)
    assert result['complete'] and result['rows'] == []
