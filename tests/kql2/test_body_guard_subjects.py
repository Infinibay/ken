"""The three guard subjects a body may state.

The legacy catalogue guarded its interning arms with ``MEMBERSHIP`` /
``NOT_MEMBER_OF`` / ``NULL_TEST`` edges.  These are the KQL 2 spellings of the
same claims, each matched against the source occurrence and not its spelling:

* ``if ($key not in $pool)`` -- a negated membership test;
* ``if ($pool[$key] == null)`` -- the *read* of a bound place at a key, tested
  against null (the element's own ``CONTAINER``/``INDEX`` facts are the evidence);
* ``if ($value == null)`` over ``let $value = call $load {};`` -- the result of a
  call the pattern bound, tested against null.
"""
from __future__ import annotations

from ken.kql2.service import search


def query(body: str, declarations: str = '') -> str:
    return ('language "kql/2"; module t; query q { ' + declarations +
            'type $unit { field $pool {} method $get { param $key {} body {' + body +
            '} } } select $unit; }')


def write(tmp_path, source: str) -> None:
    (tmp_path / 'guard.py').write_text(source)


MEMBERSHIP_GUARDED = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        if key not in self.pool:
            self.pool[key] = 1
        return self.pool[key]
'''

MEMBERSHIP_OPPOSITE = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        if key in self.pool:
            self.pool[key] = 1
        return self.pool[key]
'''

MEMBERSHIP_UNGUARDED = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        self.pool[key] = 1
        return self.pool[key]
'''

INDEX_GUARDED = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        if self.pool[key] is None:
            self.pool[key] = 1
        return self.pool[key]
'''

INDEX_OTHER_CONTAINER = '''class Subject:
    def __init__(self):
        self.pool = {}
        self.other = {}
    def get(self, key):
        if self.other[key] is None:
            self.pool[key] = 1
        return self.pool[key]
'''

INDEX_UNGUARDED = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        self.pool[key] = 1
        return self.pool[key]
'''

CALL_GUARDED = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        value = self.load()
        if value is None:
            return 1
        else:
            return 2
    def load(self):
        return None
'''

CALL_OTHER_LITERAL = '''class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        value = self.load()
        if value is 7:
            return 1
        else:
            return 2
    def load(self):
        return None
'''


MEMBERSHIP = 'if ($key not in $pool) { $pool[$key] = _ as $write; }'
INDEX = 'if ($pool[$key] == null) { $pool[$key] = _ as $write; }'
CALL = ('let $value = call $load {}; if ($value == null) { return 1; } else { return 2; }')
CALL_DECLARATION = 'callable $load { name: "load"; } '


def test_membership_negation_matches_the_guarded_write(tmp_path):
    write(tmp_path, MEMBERSHIP_GUARDED)
    result = search(tmp_path, query(MEMBERSHIP), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_membership_negation_rejects_the_opposite_polarity(tmp_path):
    write(tmp_path, MEMBERSHIP_OPPOSITE)
    result = search(tmp_path, query(MEMBERSHIP), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_membership_negation_rejects_an_unguarded_write(tmp_path):
    write(tmp_path, MEMBERSHIP_UNGUARDED)
    result = search(tmp_path, query(MEMBERSHIP), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_compared_to_null_matches(tmp_path):
    write(tmp_path, INDEX_GUARDED)
    result = search(tmp_path, query(INDEX), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_indexed_read_rejects_a_guard_on_another_container(tmp_path):
    write(tmp_path, INDEX_OTHER_CONTAINER)
    result = search(tmp_path, query(INDEX), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_indexed_read_rejects_an_unguarded_write(tmp_path):
    write(tmp_path, INDEX_UNGUARDED)
    result = search(tmp_path, query(INDEX), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_bound_call_result_compared_to_null_matches(tmp_path):
    write(tmp_path, CALL_GUARDED)
    result = search(tmp_path, query(CALL, CALL_DECLARATION), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_bound_call_result_rejects_another_literal(tmp_path):
    write(tmp_path, CALL_OTHER_LITERAL)
    result = search(tmp_path, query(CALL, CALL_DECLARATION), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result
