"""Exercise the real input-only native process, including strict request parsing."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def binary():return Path(os.environ.get('KEN_INDEX_PROBE',ROOT/('.ken/rust-migration/m2-fastembed/target-final-ci/debug/examples/index_probe'if sys.platform=='darwin'else'target/debug/examples/index_probe')))
def request():
    system='macos'if sys.platform=='darwin'else'linux'
    runtime=json.loads((ROOT/f'crates/ken-models/tests/fixtures/profile-identity/{system}.json').read_bytes())['legacy_runtime']
    return dict(format='ken-index-probe/1',grammar_manifest=str(ROOT/f'.ken/rust-migration/m3-parsers/sdk-{system}/manifest.json'),legacy_runtime=runtime,cases=[dict(id='native',operations=[dict(op='write',path='a.py',source_hex=b'def native():\n    return 1\n'.hex()),dict(op='index',paths=['a.py']),dict(op='index',paths=['a.py'])])])
def test_native_probe_indexes_and_skips_without_expected_data(tmp_path):
    payload=request();result=subprocess.run([str(binary())],input=json.dumps(payload),text=True,capture_output=True,cwd=tmp_path)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout);assert value['format']=='ken-index-probe/1'
    steps=value['cases'][0]['steps'];assert len(steps)==3
    assert steps[1]['result']['stats']['parsed']==1
    assert steps[2]['result']['stats']['unchanged']==1
    assert steps[1]['result']['events']==[['a.py','indexed']]
    assert len(steps[1]['snapshot']['tables']['ci_files'])==1
    assert steps[1]['snapshot']['tables']['ci_files'][0][1]=='a.py'
    assert steps[1]['result']['encoder_calls']==[]
def test_native_probe_rejects_oracle_answers_in_request(tmp_path):
    payload=request();payload['cases'][0]['expected']={'parsed':1}
    result=subprocess.run([str(binary())],input=json.dumps(payload),text=True,capture_output=True,cwd=tmp_path)
    assert result.returncode!=0
    assert 'expected' in result.stderr
