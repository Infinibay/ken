"""``let $value = $items[$index] writes: 2;`` — an indexed read whose place is rewritten.

An interning method reads the pool into a local, and the miss arm rewrites that same
local with the object it then stores back. The place therefore has two writes, and the
legacy catalogue said so with ``STORAGE_WRITE_COUNT(local, "2")``.  By default an indexed
capture still demands a single producer; stating ``writes: n`` is the pattern saying how
many writes the place carries, and the inventory must agree.
"""
from __future__ import annotations

import pytest

from ken.kql2.service import search

ONE_WRITE = '''class Glyph { constructor(public key:string) {} }
class Pool {
 pool:{[key:string]:Glyph}={};
 other:{[key:string]:Glyph}={};
 get(key:string):Glyph {
let result = this.pool[key];
if (result === undefined) {
this.pool[key] = result;
}
return result;
}}'''

TWO_WRITES = '''class Glyph { constructor(public key:string) {} }
class Pool {
 pool:{[key:string]:Glyph}={};
 other:{[key:string]:Glyph}={};
 get(key:string):Glyph {
let result = this.pool[key];
if (result === undefined) {
result = new Glyph(key);
this.pool[key] = result;
}
return result;
}}'''

WRONG_POOL = TWO_WRITES.replace('let result = this.pool[key];', 'let result = this.other[key];')
WRONG_KEY = TWO_WRITES.replace('let result = this.pool[key];', 'let result = this.pool["other"];')


def query(capture: str) -> str:
    return ('language "kql/2";\nmodule t;\n'
            'pattern detect(out TypeDecl $unit, out Field $pool, out Callable $lookup, '
            'out Parameter $key) {\n'
            '  type $unit {\n'
            '    field $pool {}\n'
            '    method $lookup {\n'
            '      constructor: false;\n'
            '      param $key {}\n'
            '      body {\n'
            '        ' + capture + '\n'
            '        insert $looked into $pool at $key;\n'
            '        return $looked;\n'
            '      }\n'
            '    }\n'
            '  }\n'
            '}\n'
            'query results {\n'
            '  use detect(unit: $unit, pool: $pool, lookup: $lookup, key: $key);\n'
            '  select $unit;\n'
            '}\n')


def matches(tmp_path, source: str, capture: str) -> bool:
    (tmp_path / 'pool.ts').write_text(source)
    result = search(tmp_path, query(capture), cache_mb=0)
    assert result['complete'], result
    return len(result['rows']) == 1


def test_indexed_capture_matches_a_single_producer(tmp_path):
    assert matches(tmp_path, ONE_WRITE, 'let $looked = $pool[$key];')


def test_indexed_capture_rejects_a_second_write_until_the_count_is_stated(tmp_path):
    assert not matches(tmp_path, TWO_WRITES, 'let $looked = $pool[$key];')


def test_indexed_capture_accepts_the_stated_write_count(tmp_path):
    assert matches(tmp_path, TWO_WRITES, 'let $looked = $pool[$key] writes: 2;')


def test_indexed_capture_rejects_a_different_write_count(tmp_path):
    assert not matches(tmp_path, TWO_WRITES, 'let $looked = $pool[$key] writes: 3;')


@pytest.mark.parametrize('source', [WRONG_POOL, WRONG_KEY])
def test_stated_count_still_correlates_the_container_and_the_key(tmp_path, source):
    assert not matches(tmp_path, source, 'let $looked = $pool[$key] writes: 2;')
