"""Source proof compares actual order/membership and binds its experiment inputs."""
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from tools.rust_migration.source_validate import compare_source_observations, definitions_digest

REPO=Path(__file__).resolve().parents[2]


def protocol_sample():
    reference={'definitions':[{'id':'tree','files':{'a.py':'','pkg/b.py':''},'scopes':['.']}],
        'cases':[{'id':'tree','walks':[{'scope':'.','entries':[{'path':'a.py','is_dir':False},
          {'path':'pkg','is_dir':True},{'path':'pkg/b.py','is_dir':False}],'files':['a.py','pkg/b.py']}]}]}
    sources={'core.rs':{'sha256':'a'*64,'bytes':1}}
    result={'format':'ken-source-execution/1','sources':sources,'native_sha256':'b'*64,
        'definitions_sha256':definitions_digest(reference['definitions']),
        'observations':[{'case':'tree','scope_index':0,'request':{'root':'/project','scope':'.'},
            'actual':{'format':'ken-source-observation/1','scope':'.',
                'entries':copy.deepcopy(reference['cases'][0]['walks'][0]['entries']),'errors':[]}}]}
    return reference,result,sources


def test_protocol_comparator_preserves_original_order_and_values():
    reference,actual,sources=protocol_sample()
    assert compare_source_observations(reference,actual,sources,'b'*64)==[]


@pytest.mark.parametrize('mutation',['membership','directory','order','missing','rule','source','binary','correction','duplicate'])
def test_resealed_protocol_changes_cannot_be_accepted(mutation):
    reference,actual,sources=protocol_sample();sources=copy.deepcopy(sources)
    row=actual['observations'][0];entries=row['actual']['entries']
    if mutation=='membership':entries[-1]['path']='pkg/other.py'
    elif mutation=='directory':entries[0]['is_dir']=True
    elif mutation=='order':entries.reverse()
    elif mutation=='missing':actual['observations'].clear()
    elif mutation=='rule':reference['definitions'][0]['files']['.gitignore']='*.py\n'
    elif mutation=='source':actual['sources']['core.rs']['sha256']='f'*64
    elif mutation=='binary':actual['native_sha256']='f'*64
    elif mutation=='correction':row['actual']['errors']=[{'kind':'outside_project','path':'a.py'}]
    elif mutation=='duplicate':actual['observations'].append(copy.deepcopy(row))
    assert compare_source_observations(reference,actual,sources,'b'*64),mutation


def probe():
    target=Path(os.environ.get('CARGO_TARGET_DIR',str(REPO/'.ken/rust-migration/m2-fastembed/target-final-ci')))
    path=Path(os.environ.get('KEN_SOURCE_PROBE',str(target/'release/examples/source_probe')))
    assert path.is_file(),'Build the real native source_probe before process tests'
    return path


@pytest.mark.parametrize('bad',[{'root':'relative','scope':'.'},
    {'root':'/project','scope':'.','expected':[]},{'root':'/project','scope':'.','unknown':True}])
def test_real_native_request_rejects_relative_root_and_output_injection(bad,tmp_path):
    result=subprocess.run([str(probe())],input=json.dumps(bad),text=True,capture_output=True,
        cwd=tmp_path,timeout=10)
    assert result.returncode!=0 and not result.stdout


def test_real_native_walk_works_without_python_or_project_marker(tmp_path):
    project=tmp_path/'project';(project/'src').mkdir(parents=True)
    (project/'src/main.py').write_text('print("hello")\n');(project/'.gitignore').write_text('*.tmp\n')
    (project/'secret.tmp').write_text('private')
    result=subprocess.run([str(probe())],input=json.dumps({'root':str(project),'scope':'src'}),
        text=True,capture_output=True,cwd=tmp_path,env={'PATH':str(tmp_path/'empty')},timeout=10,check=True)
    assert json.loads(result.stdout)=={'format':'ken-source-observation/1','scope':'src',
        'entries':[{'path':'src/main.py','is_dir':False}],'errors':[]}
