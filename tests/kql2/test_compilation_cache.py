from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ken.kql2 import compilation
from ken.kql2.service import search

QUERY='language "kql/2"; module t; query q { class $c {} select $c.name; }'


@pytest.fixture(autouse=True)
def clear():
    compilation.clear_compilation_cache()
    yield
    compilation.clear_compilation_cache()


def test_service_compile_reuse_does_not_memoize_results(tmp_path,monkeypatch):
    (tmp_path/'a.py').write_text('class A: pass')
    calls=[]
    original=compilation.compile
    def compile(*args,**kwargs):
        calls.append(1)
        return original(*args,**kwargs)
    monkeypatch.setattr(compilation,'compile',compile)
    first=search(tmp_path,QUERY)
    (tmp_path/'a.py').write_text('class B: pass')
    second=search(tmp_path,QUERY)
    assert first['rows']==[['A']] and second['rows']==[['B']]
    assert len(calls)==1
    assert second['analysis']['compilation_cache']['status']=='hit'
    assert second['analysis']['scanned_nodes'] > 0
    assert second['analysis']['disk_budget_mb']==400


def test_reference_plan_and_query_name_are_part_of_key(tmp_path):
    args=dict(root=tmp_path,source=QUERY,query=None,budget_bytes=100000)
    a,_,_=compilation.compile_query(**args)
    b,state,_=compilation.compile_query(**args,reference=True)
    assert state=='miss'
    assert a.program==b.program
    assert compilation.compile_query(**{**args,'query':'q'})[1]=='miss'
    assert compilation.compile_query(**args)[1]=='hit'


def test_disabled_clears_retention_and_recompiles(tmp_path):
    args=dict(root=tmp_path,source=QUERY,query=None,budget_bytes=100000)
    compilation.compile_query(**args)
    assert compilation.compile_query(**{**args,'budget_bytes':0})[1]=='disabled'
    assert compilation.compile_query(**args)[1]=='miss'


def test_error_does_not_create_database_or_poison_cache(tmp_path):
    for _ in range(2):
        with pytest.raises(ValueError):
            search(tmp_path,QUERY.replace('select $c.name','select $missing'))
    assert not (tmp_path/'.ken').exists()
    assert search(tmp_path,QUERY)['analysis']['compilation_cache']['status']=='miss'


def test_artifact_has_no_mutable_graph_references(tmp_path):
    artifact,_,_=compilation.compile_query(tmp_path,QUERY,None,budget_bytes=100000)
    with pytest.raises(FrozenInstanceError):
        artifact.program.name='changed'
    assert all(isinstance(scans,tuple) for _,scans in artifact.plans)


def test_project_lru_is_bounded():
    for i in range(12):
        compilation.compile_query(Path(f'/project/{i}'),QUERY,None,budget_bytes=100000)
    assert len(compilation._PROJECTS)==8
    assert compilation.compile_query(Path('/project/0'),QUERY,None,budget_bytes=100000)[1]=='miss'
