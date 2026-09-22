"""``insert $value into $collection at $key writes: n;`` — the insertion states its count.

The write inventory publishes, per write owner, how many indexed writes reach a
collection (``INDEXED_WRITE_COUNT``). A pattern that matches a dispatch table must reject
a registration whose handler is immediately overwritten, so the insertion states the
count it expects -- the same way ``let $read = $pool[$key] writes: 2`` states how many
writes the place a read landed in carries.

These run through the catalogue executor (``compile_source`` over the query, then the
graph ``Executor``), the path the packaged catalog itself uses.
"""
from __future__ import annotations

from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.semantic import link_project

ONE_WRITE = ('class Registry:\n'
             '    def register(self, key, handler): self.table[key] = handler\n'
             '    def dispatch(self, requested, data): return self.table[requested](data)\n')
TWO_WRITES = ('class Registry:\n'
              '    def register(self, key, handler):\n'
              '        self.table[key] = handler\n'
              '        self.table[key] = None\n'
              '    def dispatch(self, requested, data): return self.table[requested](data)\n')

REGISTER = ('method $register {{ arity: 2; param $key {{ }} param $handler {{ }} '
            'body {{ insert $handler into $table at $key writes: {count}; }} }}')
DISPATCH = ('method $dispatch {{ arity: 2; param $requested {{ }} '
            'body {{ call $table[$requested] {{ }} as $call; }} }}')


def matches(source: str, query: str) -> int:
    index = query_graph(link_project([lower_source(source, 'python', 'a.py')]))
    result = Executor(index, {}, None, 'strict').execute(compile_source(query))
    assert result['complete'], result['unknown']
    return len(result['matches'])


def bound_query(count: str) -> str:
    """The collection is a field selected before the register body."""
    return ('language "kql/2"; module t; query q { type $unit { field $table { } '
            + REGISTER.format(count=count) + ' ' + DISPATCH.format() + ' } select $unit; }')


def fresh_query(count: str) -> str:
    """The insertion introduces the storage role; the field selector then confirms it."""
    return ('language "kql/2"; module t; '
            'pattern detect(out TypeDecl $unit, out Field $table) { type $unit { '
            + REGISTER.format(count=count) + ' ' + DISPATCH.format() + ' field $table { } } } '
            'query results { use detect(unit: $unit, table: $table); select $unit, $table; }')


def test_bound_collection_count_one_accepts_a_single_write():
    assert matches(ONE_WRITE, bound_query('1')) == 1


def test_bound_collection_count_one_rejects_a_second_write():
    assert matches(TWO_WRITES, bound_query('1')) == 0


def test_bound_collection_states_the_count_it_expects():
    assert matches(TWO_WRITES, bound_query('2')) == 1


def test_fresh_collection_introduced_by_the_insertion_matches():
    assert matches(ONE_WRITE, fresh_query('1')) == 1


def test_fresh_collection_count_one_rejects_a_second_write():
    assert matches(TWO_WRITES, fresh_query('1')) == 0
