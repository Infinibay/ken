"""``return $container[$key];`` — the returned value is the element a read yielded.

The legacy catalogue stated a returned pooled object with the ``RETURNS`` /
``CONTAINER`` / ``INDEX`` chain.  This is the KQL 2 spelling of the same claim: the
method returns the element of a place the pattern bound, optionally at a key the
pattern also bound, and the access occurrence (not the spelling) is the evidence.
The interning shape -- look the key up in a pool, create on a miss, store under the
same index and hand back that element -- is what needs it.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

INSERTED = '''class Product:
    def __init__(self, key): self.key = key
class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        self.pool[key] = Product(key)
        return self.pool[key]
'''

OTHER_POOL = '''class Product:
    def __init__(self, key): self.key = key
class Subject:
    def __init__(self):
        self.pool = {}
        self.other = {}
    def get(self, key):
        self.pool[key] = Product(key)
        return self.other[key]
'''

CONSTANT_RETURN = '''class Product:
    def __init__(self, key): self.key = key
class Subject:
    def __init__(self): self.pool = {}
    def get(self, key):
        self.pool[key] = Product(key)
        return 0
'''


def query(ret: str) -> str:
    return ('language "kql/2"; module t; query q { '
            'type $unit { field $pool {} method $get { param $key {} body { '
            '$pool[$key] = _ as $write; '
            f'{ret}'
            '} } } select $unit; }')


def write(tmp_path, source: str) -> None:
    (tmp_path / 'pool.py').write_text(source)


def test_returned_element_matches_the_indexed_read(tmp_path):
    write(tmp_path, INSERTED)
    result = search(tmp_path, query('return $pool[$key];'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_returned_element_rejects_a_different_container(tmp_path):
    write(tmp_path, OTHER_POOL)
    result = search(tmp_path, query('return $pool[$key];'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_returned_element_rejects_a_value_that_is_not_an_element(tmp_path):
    write(tmp_path, CONSTANT_RETURN)
    result = search(tmp_path, query('return $pool[$key];'), cache_mb=0)
    assert result['complete'] and result['rows'] == [], result


def test_returned_element_captures_an_unbound_key_role(tmp_path):
    write(tmp_path, INSERTED)
    result = search(tmp_path, query('return $pool[$slot];'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result


def test_returned_element_accepts_a_wildcard_key(tmp_path):
    write(tmp_path, INSERTED)
    result = search(tmp_path, query('return $pool[_];'), cache_mb=0)
    assert result['complete'] and len(result['rows']) == 1, result
