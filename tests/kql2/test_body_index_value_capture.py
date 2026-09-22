"""``let $value = $container[$key];`` — an indexed read is a value the pattern names.

The legacy catalogue stated a cursor that reads the element at an index it also
advances (``ASSIGNMENT_VALUE``/``INDEX``/``CONTAINER`` plus ``STORAGE_WRITE_COUNT``
and ``RETURN_OPERAND``).  This is the KQL 2 spelling of the same claim: the read
yields the element, the place the read wrote is the value the pattern can return, and
that place must not be written again.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search


def query(steps: str) -> str:
    """The claim: read the element ``items[index]``, advance that index, return it."""
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $items { } field $index { } '
            'method $next { name: "__next__"; constructor: false; body { '
            f'{steps} '
            '} } } select $unit; }')


CLAIM = 'let $value = $items[$index]; $index = $index + 1; return $value;'

FIXTURE = ('class Cursor:\n'
           ' def __init__(self, values):\n'
           '  self.values = values\n'
           '  self.other = values\n'
           '  self.index = 0\n'
           ' def __next__(self):\n'
           '{steps}\n')


def write(tmp_path, steps: str) -> None:
    (tmp_path / 'a.py').write_text(FIXTURE.format(steps=steps))


READ = '  value = self.values[self.index]'
ADVANCE = '  self.index = self.index + 1'
RETURN = '  return value'
FULL = f'{READ}\n{ADVANCE}\n{RETURN}'


def run(tmp_path, steps: str, claim: str = CLAIM):
    write(tmp_path, steps)
    return search(tmp_path, query(claim), cache_mb=0)


def test_indexed_read_returns_the_element_it_read(tmp_path):
    result = run(tmp_path, FULL)
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_read_rejects_returning_another_value(tmp_path):
    # The cursor must return what it read, not a constant.
    result = run(tmp_path, f'{READ}\n{ADVANCE}\n  return 0')
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_rejects_a_read_without_progress(tmp_path):
    result = run(tmp_path, f'{READ}\n  self.index = self.index + 0\n{RETURN}')
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_rejects_a_reassigned_place(tmp_path):
    # ``value`` is written twice: the read is no longer the value the cursor
    # returns, which is the write inventory the legacy query asked for.
    result = run(tmp_path, f'{READ}\n  value = 0\n{ADVANCE}\n{RETURN}')
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_container_is_a_field_of_the_cursor(tmp_path):
    # The container role names a field the cursor holds: reading the element out of
    # another field of the same cursor still satisfies the claim, but reading it out
    # of a local the cursor made does not, because no field is that container.
    result = run(tmp_path, FULL.replace('self.values', 'self.other'))
    assert result['complete'] and len(result['rows']) == 1, result
    result = run(tmp_path, '  pool = self.values\n  value = pool[self.index]\n'
                           '  self.index = self.index + 1\n  return value')
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_key_correlates_with_the_advanced_field(tmp_path):
    # A field role is bound by enumeration, so ``$other`` can be the cursor's own
    # index. What the claim cannot do is read at one field and advance a strictly
    # different one: that is a different traversal.
    write(tmp_path, FULL)
    text = ('language "kql/2"; module t; query q { '
            'type $unit { field $items { } field $read_at { } field $moved { } '
            'method $next { name: "__next__"; constructor: false; body { '
            'let $value = $items[$read_at]; $moved = $moved + 1; return $value; '
            '} } } '
            'where $read_at != $moved; select $unit; }')
    result = search(tmp_path, text, cache_mb=0)
    assert result['complete'] and result['rows'] == [], result
    result = search(tmp_path, text.replace('where $read_at != $moved; ', ''), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_read_wildcard_key_accepts_any_element(tmp_path):
    result = run(tmp_path, FULL, 'let $value = $items[_]; $index = $index + 1; return $value;')
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_read_requires_a_bound_container(tmp_path):
    write(tmp_path, FULL)
    # ``$missing`` is never declared: the container of an element read must be a
    # place the pattern bound, otherwise the spelling is a typo, not evidence.
    with pytest.raises(Exception):
        search(tmp_path, query('let $value = $missing[$index]; $index = $index + 1; return $value;'),
               cache_mb=0)
