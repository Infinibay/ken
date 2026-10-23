"""Actual numeric transport is input-only and preserves Python strings/numbers."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
def binary():return Path(os.environ.get('KEN_NUMERIC_PROBE',ROOT/('.ken/rust-migration/m2-fastembed/target-final-ci/debug/examples/numeric_owner_probe'if sys.platform=='darwin'else'target/debug/examples/numeric_owner_probe')))
def request():return dict(format='ken-numeric-owner-probe/1',resources={},cases=[dict(id='stem',family='stems',kind='stem',input=dict(words=['running','café 😀','\ud800']))])
def run(value,tmp_path):return subprocess.run([str(binary())],input=json.dumps(value,ensure_ascii=True),text=True,capture_output=True,cwd=tmp_path)
def test_native_numeric_transport_has_no_python_and_preserves_scalar_and_isolated_text(tmp_path):
    actual=run(request(),tmp_path);assert actual.returncode==0,actual.stderr
    value=json.loads(actual.stdout);assert value['cases'][0]['result']==['run','café 😀','\ud800']
    assert value['metrics']['elapsed_s']>=0 and value['metrics']['max_rss_bytes']>0
@pytest.mark.parametrize('change',['top','case','duplicate','unknown','empty'])
def test_native_numeric_protocol_rejects_answers_or_ambiguous_inventory(tmp_path,change):
    value=request()
    if change=='top':value['expected']={}
    elif change=='case':value['cases'][0]['expected']={}
    elif change=='duplicate':value['cases'].append(value['cases'][0])
    elif change=='unknown':value['cases'][0]['kind']='unknown'
    else:value['cases']=[]
    actual=run(value,tmp_path);assert actual.returncode!=0 and actual.stdout==''

def test_native_cached_stem_observation_preserves_isolated_surrogates(tmp_path):
    value=request();value['cases'][0].update(kind='stem_reuse',input=dict(prefix='p:',batches=[['\ud800','😀'],['\ud800','😀']]))
    actual=run(value,tmp_path);assert actual.returncode==0,actual.stderr
    result=json.loads(actual.stdout)['cases'][0]['result']
    assert result==dict(batches=[['p:\ud800','p:😀'],['p:\ud800','p:😀']],calls=['\ud800','😀'],entries=2,capacity=32768)

def test_native_forest_prediction_preserves_overflow_category_in_json(tmp_path):
    from tools.rust_migration.numeric_reference import definitions
    case=next(c for c in definitions('forest')if c['id']=='overflow-output')
    value=request();value['cases']=[dict(case,family='forest')]
    actual=run(value,tmp_path);assert actual.returncode==0,actual.stderr
    assert json.loads(actual.stdout)['cases'][0]['result']['scores']==[{'$float':'inf'}]
