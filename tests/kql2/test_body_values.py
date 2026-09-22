"""``let`` captures the value a call produces; ``return`` consumes that value.

The IR models one value per occurrence, so the link from the captured call to the
returned occurrence goes through the binding the call flows to. An argument that
consumes a captured value is **not** accepted yet: the compiler rejects it instead
of accepting text it cannot honour.
"""
import pytest

from ken.kql2.compiler import CompileError
from ken.kql2.service import search

QUERY = '''language "kql/2"; module t; query q {
 callable $producer { name: "produce"; }
 callable $f { name: "f"; body {
  let $made = call $producer { } as $producing;
  return $made as $returned;
 } } select $producing.kind,$returned.kind;
}'''


@pytest.mark.parametrize('extension,source', [
    ('py', 'def produce():\n return 1\ndef f():\n made = produce()\n return made\n'),
    ('ts', 'function produce(): number { return 1; } function f() { const made = produce(); return made; }'),
    ('java', 'class A { int produce() { return 1; } int f() { int made = produce(); return made; } }'),
    ('cs', 'class A { int produce() { return 1; } int f() { int made = produce(); return made; } }'),
    ('go', 'package a\nfunc produce() int { return 1 }\nfunc f() int { made := produce(); return made }\n'),
    ('cpp', 'int produce() { return 1; } int f() { int made = produce(); return made; }'),
    ('rs', 'fn produce() -> i32 { return 1; } fn f() -> i32 { let made = produce(); return made; }'),
])
def test_captured_value_is_the_returned_one(tmp_path, extension, source):
    (tmp_path / f'a.{extension}').write_text(source)
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == [['call', 'return']]


@pytest.mark.parametrize('extension,source', [
    ('py', 'def produce():\n return 1\ndef f():\n return produce()\n'),
    ('ts', 'function produce(): number { return 1; } function f() { return produce(); }'),
    ('java', 'class A { int produce() { return 1; } int f() { return produce(); } }'),
    ('cs', 'class A { int produce() { return 1; } int f() { return produce(); } }'),
    ('go', 'package a\nfunc produce() int { return 1 }\nfunc f() int { return produce() }\n'),
    ('cpp', 'int produce() { return 1; } int f() { return produce(); }'),
    ('rs', 'fn produce() -> i32 { return 1; } fn f() -> i32 { return produce(); }'),
])
def test_let_captures_inline_expression_without_source_assignment(tmp_path,extension,source):
    (tmp_path / f'a.{extension}').write_text(source)
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == [['call', 'return']]


def test_another_call_is_not_the_captured_value(tmp_path):
    source = 'def produce():\n return 1\ndef other():\n return 2\ndef f():\n other()\n made = produce()\n return made\n'
    (tmp_path / 'a.py').write_text(source)
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == [['call', 'return']]


def test_returning_something_else_is_not_a_match(tmp_path):
    source = 'def produce():\n return 1\ndef f():\n made = produce()\n return 2\n'
    (tmp_path / 'a.py').write_text(source)
    assert search(tmp_path, QUERY, cache_mb=0)['rows'] == []


def test_an_argument_cannot_consume_a_captured_value_yet(tmp_path):
    (tmp_path / 'a.py').write_text('def produce():\n return 1\ndef consume(x):\n return x\n'
                                   'def f():\n made = produce()\n consume(made)\n')
    query = QUERY.replace('return $made as $returned;',
                          'call $consumer { argument $made at 0; };').replace(
        'callable $f {', 'callable $consumer { name: "consume"; }\n callable $f {')
    with pytest.raises(CompileError):
        search(tmp_path, query, cache_mb=0)
    assert not (tmp_path / '.ken').exists()
