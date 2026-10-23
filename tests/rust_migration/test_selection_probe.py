"""Real native protocol and Python-compatible JSON text at the transport boundary."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
from tools.rust_migration.selection_reference import definitions
ROOT=Path(__file__).resolve().parents[2]
def binary():return Path(os.environ.get('KEN_SELECTION_PROBE',ROOT/('.ken/rust-migration/m2-fastembed/target-final-ci/debug/examples/search_selection_probe'if sys.platform=='darwin'else'target/debug/examples/search_selection_probe')))
def request():
    case=next(c for c in definitions('ranking')if c['kind']=='document'and'\ud800😀'in c['input']['candidate']['passages'][0]['fields']['body'])
    return dict(format='ken-search-selection-probe/1',legacy_runtime={},cases=[case])
def test_native_document_transport_joins_astral_pairs_and_preserves_isolated_surrogates(tmp_path):
    actual=subprocess.run([str(binary())],input=json.dumps(request(),ensure_ascii=True),text=True,capture_output=True,cwd=tmp_path)
    assert actual.returncode==0,actual.stderr
    value=json.loads(actual.stdout);assert '\ud800😀'in value['cases'][0]['result']
    assert value['metrics']['max_rss_bytes']>0 and value['metrics']['elapsed_s']>=0
def test_native_source_view_observation_has_only_the_original_fields(tmp_path):
    case=next(c for c in definitions('context')if c['kind']=='source_views')
    value=dict(format='ken-search-selection-probe/1',legacy_runtime={},cases=[case])
    actual=subprocess.run([str(binary())],input=json.dumps(value),text=True,capture_output=True,cwd=tmp_path)
    assert actual.returncode==0,actual.stderr
    result=json.loads(actual.stdout)['cases'][0]['result']
    assert set(result)=={'candidates','query_calls'}
@pytest.mark.parametrize('change',['top','case','duplicate','kind','empty'])
def test_native_protocol_rejects_answers_and_ambiguous_inventory(tmp_path,change):
    value=request()
    if change=='top':value['expected']={}
    elif change=='case':value['cases'][0]['expected']={}
    elif change=='duplicate':value['cases'].append(value['cases'][0])
    elif change=='kind':value['cases'][0]['kind']='not_implemented'
    else:value['cases']=[]
    actual=subprocess.run([str(binary())],input=json.dumps(value),text=True,capture_output=True,cwd=tmp_path)
    assert actual.returncode!=0 and actual.stdout==''
