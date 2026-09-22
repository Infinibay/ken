"""Public KQL2 has opt-in execution limits, independent of cache capacity."""
import argparse
import inspect
import pytest
from ken.kql2 import parse
from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.kql2.service import search
from ken.kql2.cli import configure
from ken.structural_store import Store
from ken.structural.frontend import lower_source


def graph_fixture(store):
 source=''.join(f'class Class{i}:\n def work(self): pass\n' for i in range(40))
 unit=store.put_unit('u',lower_source(source,'python','sample.py'),'h','v')
 return store.publish([unit],expected_parent=None)

HEADER='language "kql/2"; module unlimited; '
QUERIES=[
 'query q {class $c {} select $c;}',
 'query q {{class $c {name:/Class1/;} } or {class $c {name:/Class2/;}} select $c;}',
]

@pytest.mark.parametrize('reference',[False,True])
@pytest.mark.parametrize('query',QUERIES)
@pytest.mark.parametrize('kwargs',[{},dict(timeout_ms=None,max_states=None,max_rows=None)])
def test_unlimited_sql_and_union(reference,query,kwargs):
 with Store() as store:
  result=execute(compile(parse(HEADER+query)),store,graph_fixture(store),reference=reference,**kwargs)
  assert result.complete,result
  assert len(result.rows)==(40 if query==QUERIES[0] else 22)

@pytest.mark.parametrize('reference',[False,True])
@pytest.mark.parametrize('limits',[dict(max_states=1),dict(max_rows=1),dict(timeout_ms=0),dict(cancelled=lambda:True)])
def test_explicit_limits_and_cancellation_still_stop_execution(reference,limits):
 with Store() as store:
  result=execute(compile(parse(HEADER+QUERIES[0])),store,graph_fixture(store),reference=reference,**limits)
  assert not result.complete
  assert result.reason


GRAPH='''language "kql/2"; module graph;
query q {class $c {method $m {param $p {reassigned:false;}}}select $c,$p;}
'''
SIMPLE=HEADER+'query q {class $c {} select $c.name;}'

@pytest.mark.parametrize('query',[SIMPLE,GRAPH])
@pytest.mark.parametrize('reference',[False,True])
def test_service_unlimited_disk_and_result_cache(tmp_path,query,reference):
 (tmp_path/'a.py').write_text('class A:\n def f(self,x): return x\nclass B:\n def f(self,x): return x\n')
 first=search(tmp_path,query,reference=reference,timeout_ms=None,max_states=None,max_rows=None)
 warm=search(tmp_path,query,reference=reference)
 assert first['complete'] and warm['complete']
 assert first['rows']==warm['rows'] and len(warm['rows'])==2
 if not reference:assert warm['analysis']['result_cache']=='disk_hit'
 limited=search(tmp_path,query,max_rows=1,reference=reference)
 assert not limited['complete'],limited
 assert len(limited['rows'])<=1

@pytest.mark.parametrize('limits',[dict(max_states=1),dict(max_rows=1),dict(timeout_ms=0)])
def test_graph_explicit_budgets(tmp_path,limits):
 (tmp_path/'a.py').write_text('class A:\n def f(self,x): return x\nclass B:\n def f(self,x): return x\n')
 assert not search(tmp_path,GRAPH,cache_mb=0,**limits)['complete']


def test_public_api_and_cli_defaults_are_unlimited():
 for function in (search,execute):
  parameters=inspect.signature(function).parameters
  assert all(parameters[name].default is None for name in ('timeout_ms','max_states','max_rows'))
 parser=argparse.ArgumentParser();configure(parser)
 args=parser.parse_args(['sample.kql'])
 assert args.timeout_ms is None and args.max_states is None and args.max_rows is None


def test_graph_cancellation_survives_unlimited_budgets():
 with Store() as store:
  snapshot=graph_fixture(store)
  result=execute(compile(parse(GRAPH)),store,snapshot,cancelled=lambda:True)
  assert not result.complete and result.reason=='cancelled'


@pytest.mark.parametrize('limit',[None,2])
def test_mcp_forwards_optional_row_limit(monkeypatch,tmp_path,limit):
 import ken.mcp.server as server
 import ken.kql2.service as service
 captured={}
 def fake_search(*args,**kwargs):captured.update(kwargs);return {'complete':True}
 monkeypatch.setattr(service,'search',fake_search)
 monkeypatch.setattr(server,'_PROJECT_ROOT',tmp_path)
 server.ken_find(query=GRAPH,scope='structure',query_language='kql/2',limit=limit)
 assert captured['max_rows'] is limit
 assert captured['timeout_ms'] is None
