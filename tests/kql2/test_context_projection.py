import json
from dataclasses import asdict
import pytest
from ken.structural.frontend import lower_source
from ken.structural_store import Store
from ken.structural_store.operations import load
from ken.structural_store.migrations import migrate
from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute


@pytest.mark.parametrize('language,source', [
 ('python','def f(x):\n while x:\n  x=(x-1)\n return x\ndef g():\n return 2\n'),
 ('typescript','function f(x:number) { while(x) { x=(x-1); } return x; } function g() { return 2; }'),
 ('java','class A { int f(int x) { while(x>0) { x=(x-1); } return x; } int g() {return 2;} }'),
 ('csharp','class A { int f(int x) { while(x>0) { x=(x-1); } return x; } int g() {return 2;} }'),
 ('cpp','int f(int x) { while(x>0) { x=(x-1); } return x; } int g() {return 2;}'),
 ('go','package a\nfunc f(x int) int { for x>0 { x=(x-1) }; return x }; func g() int {return 2}'),
 ('rust','fn f(mut x:i32)->i32 { while x>0 { x=(x-1); } return x; } fn g()->i32 {return 2;}'),
])
def test_indexed_context_preserves_owner_parents_ranges_and_operations(language,source,monkeypatch):
 ir=lower_source(source,language,'a')
 owner=next(e.id for e in ir.entities.values() if e.kind=='CALLABLE' and e.name=='f')
 with Store() as store:
  unit=store.put_unit('a',ir,'h','v')
  monkeypatch.setattr(store,'load_unit',lambda *_:pytest.fail('indexed context should not decompress full source unit'))
  result=load(store,unit,owner)
  expected={o.id:asdict(o) for o in ir.operations if o.owner==owner}
  assert {o.id:asdict(o) for o in result.operations} == expected
  assert all(o.owner==owner for o in result.operations)
  plan=store.db.execute('EXPLAIN QUERY PLAN SELECT * FROM k2_operations WHERE unit_id=? AND owner=?',(unit,owner)).fetchall()
  assert any('k2_operations_owner' in str(row) for row in plan)


def test_schema_four_unit_is_projected_lazily_once(tmp_path,monkeypatch):
 with Store(tmp_path/'s.db') as store:
  ir=lower_source('def f():\n return 1\n','python','a.py')
  unit=store.put_unit('a',ir,'h','v')
  migrate(store.db,4)
  assert store.load_unit(unit).to_dict()==ir.to_dict()
  migrate(store.db,5)
  assert store.db.execute('SELECT count(*) FROM k2_operation_units').fetchone()[0]==0
  assert load(store,unit).operations
  monkeypatch.setattr(store,'load_unit',lambda *_:pytest.fail('projection should be reused'))
  assert load(store,unit).operations


def test_source_operation_selection_does_not_require_global_linking():
 with Store() as store:
  ir=lower_source('def f():\n return 1\n','python','a.py')
  unit=store.put_unit('a',ir,'h','v')
  snapshot=store.publish([unit],expected_parent=None)
  query=compile(parse('language "kql/2"; module t; query q { operation $o {kind:"return";} select $o.line; }'))
  assert execute(query,store,snapshot).rows == [(2,)]
  assert store.db.execute('SELECT count(*) FROM k2_analysis').fetchone()[0] == 0
