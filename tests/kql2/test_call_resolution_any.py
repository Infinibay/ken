"""``resolution: any;`` — the occurrence is what the clause is about, with no status filter.

The legacy catalogue never constrained how a call resolved: a delegation is a delegation
whether the callee was accredited by a declaration or stayed a member call on an unknown
receiver.  The mediator fixtures spell exactly that, and the same site resolves
``unresolved`` in Python/JavaScript but ``resolved`` in Go/Rust/Java/C++.

``resolution:`` therefore accepts ``resolved``, ``unresolved``, ``ambiguous`` and ``any``;
omitting the constraint is *not* the same thing as ``any`` -- it asserts the callee
resolved to a callable, while ``any`` filters nothing.  A wildcard spelling such as
``resolution: _;`` stays a compile error.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

UNRESOLVED = ('class C:\n'
              ' def __init__(self, a):\n'
              '  self.first = a\n'
              ' def run(self, tag):\n'
              '  self.first.apply(tag)\n')

RESOLVED = ('class T:\n'
            ' def apply(self, tag):\n'
            '  pass\n'
            '\n'
            '\n'
            'class C:\n'
            ' def __init__(self, a: T):\n'
            '  self.first = a\n'
            ' def run(self, tag):\n'
            '  self.first.apply(tag)\n')


def query(constraint: str) -> str:
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $first {} method $run { '
            'body { call $inner { receiver: $first; ' + constraint + ' }; } } } select $unit; }')


def write(tmp_path, source: str) -> None:
    (tmp_path / 'a.py').write_text(source)


def matches(tmp_path, constraint: str, source: str) -> bool:
    write(tmp_path, source)
    result = search(tmp_path, query(constraint), cache_mb=0)
    assert result['complete'], result
    return bool(result['rows'])


@pytest.mark.parametrize('source', [UNRESOLVED, RESOLVED], ids=['unresolved', 'resolved'])
def test_any_accepts_either_status(tmp_path, source):
    assert matches(tmp_path, 'resolution: any;', source)


def test_unresolved_rejects_the_resolved_occurrence(tmp_path):
    assert matches(tmp_path, 'resolution: unresolved;', UNRESOLVED)
    assert not matches(tmp_path, 'resolution: unresolved;', RESOLVED)


def test_resolved_rejects_the_unresolved_occurrence(tmp_path):
    assert matches(tmp_path, 'resolution: resolved;', RESOLVED)
    assert not matches(tmp_path, 'resolution: resolved;', UNRESOLVED)


def test_omitting_the_constraint_asks_for_a_resolved_callee(tmp_path):
    # No constraint is not ``any``: the absent constraint is the accredited-callee claim.
    assert matches(tmp_path, '', RESOLVED)
    assert not matches(tmp_path, '', UNRESOLVED)


def test_a_wildcard_status_is_still_refused(tmp_path):
    write(tmp_path, UNRESOLVED)
    with pytest.raises(Exception):
        search(tmp_path, query('resolution: _;'), cache_mb=0)
