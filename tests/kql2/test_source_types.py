import pytest

from ken.kql2.service import search
from ken.kql2.compiler import CompileError


@pytest.mark.parametrize('extension,source,matcher', [
    ('py','def f(x: str): pass','string'),
    ('java','class A { void f(String x) {} }','string'),
    ('ts','function f(x: string) {}','string'),
    ('cs','class A { void f(string x) {} }','string'),
    ('cpp','void f(int x) {}','integer'),
    ('go','package a\nfunc f(x int) {}','integer'),
    ('rs','fn f(x: i32) {}','integer'),
    ('py','def f(x: list[str]): pass','list<string>'),
    ('go','package a\nfunc f(x map[string]int) {}','map<string,integer>'),
    ('rs','fn f(x: Vec<i32>) {}','list<integer>'),
    ('ts','function f(x: string[]) {}','array<string>'),
])
def test_typed_parameters_across_languages(tmp_path,extension,source,matcher):
    (tmp_path/f'a.{extension}').write_text(source)
    query = 'language "kql/2"; module t; query q { callable $f { param $p { type: '+matcher+'; } } select $p.name; }'
    result = search(tmp_path,query,cache_mb=0)
    assert result['complete'] and result['rows'] == [['x']]


def test_any_unknown_and_missing_type_are_different(tmp_path):
    (tmp_path/'a.ts').write_text('function a(x: any) {} function b(x: unknown) {} function c(x) {}')
    def query(constraint):
        return search(tmp_path,'language "kql/2"; module t; query q { callable $f { param $p { '+constraint+'; } } select $f.name; }',cache_mb=0)
    assert query('type: any')['rows'] == [['a']]
    assert query('type: unknown')['rows'] == [['b']]
    assert query('type_status: unknown')['rows'] == [['c']]
    assert query('type: string')['unknown_candidates'] == 1


def test_return_descriptor_preserves_integer_width(tmp_path):
    (tmp_path/'a.rs').write_text('fn f() -> u64 { 1 }')
    result = search(tmp_path,'language "kql/2"; module t; query q { callable $f { return_type: integer; } select $f.return_type; }',cache_mb=0)
    assert result['rows'][0][0]['bits'] == 64
    assert result['rows'][0][0]['signed'] is False


def test_shadowed_primitive_annotation_is_not_a_builtin(tmp_path):
    (tmp_path/'a.py').write_text('class str: pass\ndef f(x: str): pass')
    result = search(tmp_path,'language "kql/2"; module t; query q { callable $f { param $p { type: string; } } select $p; }',cache_mb=0)
    assert result['rows'] == []


def test_type_matcher_inside_negation(tmp_path):
    (tmp_path/'a.py').write_text('def a(x: str): pass\ndef b(x: int): pass')
    result = search(tmp_path,'language "kql/2"; module t; query q { callable $f { not exists { param $p { type: string; } } } select $f.name; }',cache_mb=0)
    assert result['rows'] == [['b']]


@pytest.mark.parametrize('matcher',['nonsense','map<string>','integer<string>'])
def test_invalid_matcher_fails_before_creating_store(tmp_path,matcher):
    with pytest.raises(CompileError):
        search(tmp_path,'language "kql/2"; module t; query q { param $p { type: '+matcher+'; } select $p; }')
    assert not (tmp_path/'.ken').exists()
