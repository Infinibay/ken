import pytest
from ken.common_ast import normalize
from ken.structural.frontend import lower_source
from ken.structural_store import Store
from ken.structural_store.common_ast import load, View
from ken.structural_store.migrations import migrate
from .sources import SOURCES


@pytest.mark.parametrize('language',SOURCES)
def test_persistent_common_ast_roundtrip_and_indexed_subtree(language,tmp_path,monkeypatch):
 ir=lower_source(SOURCES[language],language,'a')
 expected=normalize(ir)
 with Store(tmp_path/'s.db') as store:
  unit=store.put_unit('a',ir,'h','v')
 with Store(tmp_path/'s.db') as store:
  monkeypatch.setattr(store,'load_unit',lambda *_:pytest.fail('common AST should be read from its indexed tables'))
  actual=load(store,unit)
  assert actual==expected
  view=View(store,unit)
  ret=next(view.nodes(kind='return'))
  assert list(view.nodes(parent=ret.id))==[n for n in expected.nodes if n.parent==ret.id]
  assert list(view.nodes(descendant_of=ret))==[n for n in expected.nodes if ret.id<n.id<ret.subtree_end]
  y=next(s for s in expected.symbols if s.name=='y')
  assert view.references_to(y.id)==tuple(r for r in expected.references if r.symbol==y.id)
  assert y in view.declarations(y.scope,'y',100000)
  plan=store.db.execute('EXPLAIN QUERY PLAN SELECT symbol_id FROM k2_ast_symbols WHERE unit_id=? AND scope=? AND name=? ORDER BY visible_from DESC LIMIT 1',(unit,y.scope,0)).fetchall()
  assert any('k2_ast_symbol_lookup' in str(row) for row in plan)


def test_strings_interned_once_and_deleted_with_unit(tmp_path):
 with Store(tmp_path/'s.db') as store:
  ir=lower_source('def f():\n x=1\n x=x+1\n return x\n','python')
  unit=store.put_unit('a',ir,'h','v')
  assert store.db.execute("SELECT count(*) FROM k2_ast_strings WHERE value='x'").fetchone()[0]==1
  store.db.execute('DELETE FROM k2_units WHERE unit_id=?',(unit,))
  for table in ('nodes','strings','scopes','symbols','references','links','units'):
   assert store.db.execute('SELECT count(*) FROM k2_ast_'+table).fetchone()[0]==0


def test_schema_five_migrates_lazily_without_reparsing(tmp_path):
 with Store(tmp_path/'s.db') as store:
  ir=lower_source('def f(x):\n return x\n','python')
  unit=store.put_unit('a',ir,'h','v')
  migrate(store.db,5)
  assert store.load_unit(unit).to_dict()==ir.to_dict()
  migrate(store.db)
  assert not store.db.execute('SELECT 1 FROM k2_ast_units').fetchone()
  assert load(store,unit)==normalize(ir)
  assert store.db.execute('SELECT 1 FROM k2_ast_units').fetchone()


def test_old_unit_projection_can_use_working_memory_when_retention_is_full(tmp_path):
 with Store(tmp_path/'s.db') as store:
  ir=lower_source('def f(x):\n return x\n','python')
  unit=store.put_unit('a',ir,'h','v')
  store.db.execute('DELETE FROM k2_ast_units')
  store.limit_bytes=1
  assert load(store,unit)==normalize(ir)
  assert not store.db.execute('SELECT 1 FROM k2_ast_units').fetchone()
