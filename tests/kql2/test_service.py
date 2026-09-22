import json
import os
import subprocess
import sys

import pytest

from ken.kql2.compiler import CompileError
from ken.kql2.service import search

QUERY='''language "kql/2"; module test;
query q { class $c { method $m { name: "work"; param $p { position: 0; } } } select $c.name,$p.name; }
'''
SOURCE='class Worker:\n def work(self, task):\n  return task\n'


def test_incremental_edit_add_delete_equals_rebuild(tmp_path):
    (tmp_path/'a.py').write_text(SOURCE)
    first=search(tmp_path,QUERY)
    assert first['rows']==[['Worker','task']]
    assert first['analysis']['parsed_units']==1
    warm=search(tmp_path,QUERY)
    assert warm['rows']==first['rows']
    assert warm['analysis']['parsed_units']==0
    assert warm['analysis']['reused_units']==1
    (tmp_path/'a.py').write_text(SOURCE.replace('Worker','Other'))
    (tmp_path/'b.py').write_text(SOURCE)
    edited=search(tmp_path,QUERY)
    assert edited['analysis']['parsed_units']==2
    assert sorted(edited['rows'])==sorted(search(tmp_path,QUERY,cache_mb=0)['rows'])
    (tmp_path/'a.py').unlink()
    deleted=search(tmp_path,QUERY)
    assert deleted['rows']==first['rows']
    assert deleted['analysis']['parsed_units']==0
    assert deleted['analysis']['reused_units']==1


def test_optional_entity_locations_are_snapshot_scoped_and_cache_independent(tmp_path):
    path = tmp_path / 'a.py'
    path.write_text('def save():\n return 1\n')
    query = 'language "kql/2"; module demo; query q {edge ENTITY($f,"CALLABLE"); select $f;}'
    cold = search(tmp_path, query, include_entities=True)
    identity = cold['rows'][0][0]
    assert cold['entities'][identity] == {'local_id': identity, 'kind': 'CALLABLE',
                                         'name': 'save', 'path': 'a.py', 'line': 1}
    plain = search(tmp_path, query)
    assert 'entities' not in plain and plain['rows'] == cold['rows']
    warm = search(tmp_path, query, include_entities=True)
    assert warm['entities'] == cold['entities']
    path.write_text('\ndef save():\n return 1\n')
    changed = search(tmp_path, query, include_entities=True)
    assert next(iter(changed['entities'].values()))['line'] == 2
    assert identity not in changed['entities']


@pytest.mark.parametrize('budget',[0,.001,.1,500])
def test_budget_equivalence(tmp_path,budget):
    (tmp_path/'a.py').write_text(SOURCE)
    result=search(tmp_path,QUERY,cache_mb=budget)
    assert result['rows']==[['Worker','task']]
    if budget in (0,.001):
        assert result['analysis']['ephemeral']
    if budget==0:
        assert not (tmp_path/'.ken').exists()


def test_invalid_query_does_not_touch_database(tmp_path):
    with pytest.raises(CompileError):
        search(tmp_path,'language "kql/2"; module t; query q { class $c { body { return $x; } } select $c; }')
    assert not (tmp_path/'.ken').exists()


def test_live_read_hash_not_mtime(tmp_path):
    file=tmp_path/'a.py'
    file.write_text(SOURCE)
    before=file.stat()
    search(tmp_path,QUERY)
    file.write_text(SOURCE.replace('Worker','Warker'))
    os.utime(file,ns=(before.st_atime_ns,before.st_mtime_ns))
    result=search(tmp_path,QUERY)
    assert result['rows']==[['Warker','task']]
    assert result['analysis']['parsed_units']==1


def test_frontend_version_invalidation(tmp_path,monkeypatch):
    (tmp_path/'a.py').write_text(SOURCE)
    search(tmp_path,QUERY)
    monkeypatch.setattr('ken.kql2.service.frontend_fingerprint',lambda:'changed')
    assert search(tmp_path,QUERY)['analysis']['parsed_units']==1


def test_paths_and_unsupported_coverage(tmp_path):
    (tmp_path/'a.py').write_text(SOURCE)
    (tmp_path/'b.c').write_text('int main() {}')
    result=search(tmp_path,QUERY,cache_mb=0)
    assert result['coverage_complete'] is False
    assert result['analysis']['skipped'][0]['path']=='b.c'
    with pytest.raises(ValueError):
        search(tmp_path,QUERY,path='../outside')


def test_cold_warm_partial_coverage_equal(tmp_path):
    (tmp_path/'a.py').write_text('class Broken(:\n def work(self, task): return task\n')
    a=search(tmp_path,QUERY)
    b=search(tmp_path,QUERY)
    assert a['coverage_complete']==b['coverage_complete']
    assert a['rows']==b['rows']


def test_module_cli(tmp_path):
    (tmp_path/'a.py').write_text(SOURCE)
    query_file=tmp_path/'q.kql'
    query_file.write_text(QUERY)
    process=subprocess.run([sys.executable,'-m','ken.kql2',str(query_file),'--root',str(tmp_path),'--cache-mb','0'],capture_output=True,text=True)
    assert process.returncode==0,process.stderr
    assert json.loads(process.stdout)['rows']==[['Worker','task']]
