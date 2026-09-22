import pytest

from ken.kql2.service import search
from ken.kql2.compiler import CompileError

QUERY = '''language "kql/2"; module t; query q {
  callable $f { name: "f"; body {
    var $y { name: "y"; }
    $y = $y + 1 as $update;
    return $y as $result;
  } } select $f.name,$update.kind,$result.kind;
}'''


def execute(tmp_path, source, query=QUERY, extension='py'):
    (tmp_path/f'a.{extension}').write_text(source)
    return search(tmp_path,query,cache_mb=0,timeout_ms=10000)


@pytest.mark.parametrize('extension,source', [
    ('py','def f():\n y=0\n print("noise")\n y=y+1\n return y\n'),
    ('java','class A { int f() { int y=0; log(); y=y+1; return y; } }'),
    ('ts','function f() { let y=0; log(); y=y+1; return y; }'),
    ('cpp','int f() { int y=0; log(); y=y+1; return y; }'),
    ('cs','class A { int f() { int y=0; Log(); y=y+1; return y; } }'),
    ('go','package a\nfunc f() int { y:=0; log(); y=y+1; return y }'),
    ('rs','fn f() -> i32 { let mut y=0; log(); y=y+1; return y; }'),
])
def test_cfg_subsequence_tolerates_unrelated_operations(tmp_path,extension,source):
    result = execute(tmp_path,source,extension=extension)
    assert result['complete'] and result['rows'] == [['f','assign','return']]


@pytest.mark.parametrize('noise,expected', [('',True),('# comment\n ',True),('pass\n ',False),('print("noise")\n ',False)])
def test_adjacent_uses_source_statement_groups(tmp_path,noise,expected):
    result = execute(tmp_path,'def f():\n y=0\n '+noise+'y=y+1\n return y\n',QUERY.replace('body {','body adjacent {'))
    assert bool(result['rows']) is expected


def test_lexical_adjacent_only_constrains_one_gap(tmp_path):
    query = QUERY.replace('$y = $y + 1','adjacent;\n $y = $y + 1')
    source = 'def f():\n y=0\n y=y+1\n print("after update")\n return y\n'
    assert execute(tmp_path,source,query)['rows'] == [['f','assign','return']]


def test_dead_suffix_does_not_match(tmp_path):
    source = 'def f():\n y=0\n return y\n y=y+1\n return y\n'
    assert execute(tmp_path,source)['rows'] == []


def test_does_not_mix_opposite_branches(tmp_path):
    source = 'def f(flag):\n y=0\n if flag:\n  y=y+1\n else:\n  return y\n return 0\n'
    assert execute(tmp_path,source)['rows'] == []


def test_partial_cfg_is_unknown_not_false(tmp_path):
    result = execute(tmp_path,'def f():\n y=0\n try:\n  y=y+1\n except Exception:\n  pass\n return y\n')
    assert result['rows'] == [] and result['unknown_candidates'] > 0


@pytest.mark.parametrize('body', ['adjacent; return 1;', 'return 1; adjacent;', 'return $missing;'])
def test_invalid_body_fails_before_store(tmp_path,body):
    with pytest.raises(CompileError):
        search(tmp_path,'language "kql/2"; module t; query q { callable $f { body {'+body+'} } select $f; }')
    assert not (tmp_path/'.ken').exists()


def test_body_plan_roundtrips_disk(tmp_path):
    from ken.kql2.compilation import clear_compilation_cache
    (tmp_path/'a.py').write_text('def f():\n y=0\n y=y+1\n return y\n')
    first = search(tmp_path,QUERY)
    clear_compilation_cache()
    second = search(tmp_path,QUERY)
    assert first['rows'] == second['rows'] == [['f','assign','return']]
    assert second['analysis']['compilation_cache']['status'] == 'disk_hit'


def test_parenthesized_binding_operand(tmp_path):
    result=execute(tmp_path,'def f():\n y=0\n y=(y)+1\n return (y)\n')
    assert result['rows'] == [['f','assign','return']]


def test_explicit_read_uses_the_same_binding_occurrence(tmp_path):
    query=QUERY.replace('$y + 1','read($y) + 1').replace('return $y','return read($y)')
    assert execute(tmp_path,'def f():\n y=0\n y=y+1\n return y\n',query)['rows'] == [['f','assign','return']]


def test_shadowed_binding_does_not_connect_to_outer_return(tmp_path):
    source='function f() { let y=0; { let y=7; y=y+1; } return y; }'
    assert not execute(tmp_path,source,extension='ts')['rows']
