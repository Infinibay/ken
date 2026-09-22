import pytest
from ken.kql2.service import search

QUERY = '''language "kql/2"; module t; query q {
 callable $target { name: "g"; }
 callable $f { name: "f"; param $y { name: "y"; } body {
  call $target { argument $y at 0; } as $invoke;
  return $y;
 } } select $invoke.kind;
}'''

@pytest.mark.parametrize('extension,source', [
 ('py','def g(x):\n return x\ndef f(y):\n print("noise")\n g(y)\n print("more noise")\n return y\n'),
 ('ts','function g(x: number) { return x; } function f(y: number) { log(); g(y); log(); return y; }'),
 ('java','class A { int g(int x) { return x; } int f(int y) { log(); g(y); log(); return y; } }'),
 ('cs','class A { int g(int x) { return x; } int f(int y) { log(); g(y); log(); return y; } }'),
 ('go','package a\nfunc g(x int) int { return x }\nfunc f(y int) int { log(); g(y); log(); return y }'),
 ('cpp','int g(int x) { return x; } int f(int y) { log(); g(y); log(); return y; }'),
 ('rs','fn g(x: i32) -> i32 { return x; } fn f(y: i32) -> i32 { log(); g(y); log(); return y; }'),
])
def test_target_and_argument_across_languages(tmp_path,extension,source):
 (tmp_path/f'a.{extension}').write_text(source)
 result=search(tmp_path,QUERY,cache_mb=0)
 assert result['rows'] == [['call']]

@pytest.mark.parametrize('call,argument,expected', [
 ('g(4)','argument $y at 0;',False),
 ('g(y)','argument $y at 1;',False),
 ('g(4)','argument 4 at 0;',True),
 ('g(x=y)','argument $y at name("x");',True),
 ('g(x=y)','argument $y at 0;',False),
 ('g(y)','argument $y at any;',True),
 ('other(y)','argument $y at 0;',False),
])
def test_argument_constraints_and_wrong_target(tmp_path,call,argument,expected):
 (tmp_path/'a.py').write_text('def g(x):\n return x\ndef other(x):\n return x\ndef f(y):\n '+call+'\n return y\n')
 result=search(tmp_path,QUERY.replace('argument $y at 0;',argument),cache_mb=0)
 assert bool(result['rows']) is expected


def test_unexpanded_argument_pack_is_unknown(tmp_path):
 (tmp_path/'a.py').write_text('def g(x):\n return x\ndef f(y):\n g(*y)\n return y\n')
 result=search(tmp_path,QUERY,cache_mb=0)
 assert not result['rows'] and result['unknown_candidates'] > 0


@pytest.mark.parametrize('middle,expected,unknown', [
 ('',True,False), ('h(y)',True,False), ('g(y)',False,False),
 ('unresolved(y)',False,True),
 ('if flag:\n  g(y)',False,False),
 ('if flag:\n  g(y)\n  return 0',True,False),
])
def test_forbid_direct_call_on_all_connecting_paths(tmp_path,middle,expected,unknown):
 query = QUERY.replace('return $y;', 'gap until next { forbid call($target, through: direct); } return $y;')
 source = 'def g(x):\n return x\ndef h(x):\n return x\ndef f(y,flag):\n g(y)\n '
 source += middle.replace('\n','\n ')+'\n return y\n'
 (tmp_path/'a.py').write_text(source)
 # With another g call present, the query could choose the final occurrence as
 # its first anchor. Bind the first call's line explicitly to test the interval.
 query = query.replace('gap until next', 'where $invoke.line == 6; gap until next')
 result=search(tmp_path,query,cache_mb=0)
 assert bool(result['rows']) is expected
 assert bool(result['unknown_candidates']) is unknown
