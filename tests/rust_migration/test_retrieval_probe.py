"""Exercise actual native retrieval operations without expected answers in requests."""
import json,os,subprocess,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
def binary():return Path(os.environ.get('KEN_RETRIEVAL_KERNEL_PROBE',ROOT/('.ken/rust-migration/m2-fastembed/target-final-ci/debug/examples/retrieval_kernel_probe'if sys.platform=='darwin'else'target/debug/examples/retrieval_kernel_probe')))
def request():return dict(format='ken-retrieval-kernel-probe/1',cases=[dict(id='query',kind='request',input=dict(query='𐐀😀')),dict(id='score',kind='bm25f',input=dict(frequencies={'body':3},lengths={'body':20},averages={'body':10.},document_frequency=2,documents=10))])
def test_actual_native_query_and_postings_have_measured_results(tmp_path):
    actual=subprocess.run([str(binary())],input=json.dumps(request()),text=True,capture_output=True,cwd=tmp_path)
    assert actual.returncode==0,actual.stderr
    value=json.loads(actual.stdout);assert value['format']=='ken-retrieval-kernel-probe/1'and value['cases'][0]['result']['query']=='𐐀😀'
    assert value['cases'][1]['result']>0
    assert value['metrics']['max_rss_bytes']>0 and value['metrics']['elapsed_s']>=0

@pytest.mark.parametrize('mutation',['top','case','duplicate','kind'])
def test_actual_native_protocol_rejects_expectations_and_ambiguous_cases(tmp_path,mutation):
    payload=request()
    if mutation=='top':payload['expected']={}
    elif mutation=='case':payload['cases'][0]['expected']={}
    elif mutation=='duplicate':payload['cases'][1]['id']='query'
    else:payload['cases'][0]['kind']='unimplemented'
    actual=subprocess.run([str(binary())],input=json.dumps(payload),text=True,capture_output=True,cwd=tmp_path)
    assert actual.returncode!=0 and actual.stdout==''
