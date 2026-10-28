from pathlib import Path
import gzip,json,os,shutil,subprocess
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_native_python_probe_accepts_inputs_and_rejects_answers_and_bad_grammar(tmp_path):
    from tools.rust_migration.python_witnesses_host import reference
    binary=ROOT/'target/debug/examples/python_witnesses_probe'
    original=reference(ROOT);frame=original['cases'][0]
    request=dict(grammar_manifest=os.environ['KEN_GRAMMAR_MANIFEST'],cases=[dict(id=frame['id'],input=frame['input'])])
    def run(value):return subprocess.run([binary],input=json.dumps(value),text=True,capture_output=True)
    result=run(request);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==dict(format='ken-python-witnesses-native/1',cases=[dict(id=frame['id'],result=frame['result'])])
    assert run(request|dict(expected={})).returncode!=0
    assert run(request|dict(cases=[request['cases'][0]|dict(result=frame['result'])])).returncode!=0
    assert run(request|dict(cases=[dict(id=frame['id'],input=frame['input']|dict(expected={}))])).returncode!=0
    bad=tmp_path/'manifest.json';bad.write_text('{}')
    assert run(request|dict(grammar_manifest=str(bad))).returncode!=0
    assert run(request|dict(cases=[])).returncode!=0

def test_missing_python_capture_rejects_summary(tmp_path):
    from tools.rust_migration.python_witnesses_host import verify_capture
    (tmp_path/'summary.json').write_text('{"passed":true}');assert verify_capture(tmp_path,ROOT)
@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_PYTHON_WITNESSES_PACKET',ROOT/'.ken/rust-migration/python-operation-witnesses/packet'))
    out=tmp_path/'packet';shutil.copytree(source,out);return out

def test_actual_python_capture_is_input_only_and_native(packet):
    from tools.rust_migration.python_witnesses_host import verify_capture
    assert not verify_capture(packet,ROOT)
@pytest.mark.parametrize('change',['input-answer','witness','owner','binary','owned','grammar','original','compat','review','parent'])
def test_resealed_python_capture_rejects(packet,change):
    from tools.rust_migration.python_witnesses_host import verify_capture
    from tools.rust_migration.native_json import identity
    assert not verify_capture(packet,ROOT)
    out=packet/'python-witnesses';capture=out/'native';execution=capture/'execution.json';record=json.loads(execution.read_bytes())
    if change=='input-answer':
        path=capture/'inputs.json';value=json.loads(path.read_bytes());value['expected']={};path.write_text(json.dumps(value));record['request_sha256']=identity(path)['sha256']
    elif change in('witness','owner'):
        path=capture/'stdout.json';value=json.loads(path.read_bytes())
        if change=='witness':value['cases'][0]['result'][0]['cold']=['invented']
        else:value['cases'][0]['result'][0]['key']['path']='foreign.py'
        path.write_text(json.dumps(value));record['stdout_sha256']=identity(path)['sha256']
    elif change=='binary':(out/'bin/python_witnesses_probe').write_bytes(b'changed')
    elif change=='owned':record['owned_before']['grammar-manifest']['bytes']+=1;record['owned_after']['grammar-manifest']['bytes']+=1
    elif change=='grammar':
        (out/'grammar-manifest').write_text('{}');record['owned_before']['grammar-manifest']=identity(out/'grammar-manifest');record['owned_after']['grammar-manifest']=identity(out/'grammar-manifest')
    elif change=='original':(out/'ORIGINAL.json.gz').write_bytes(b'changed')
    elif change=='compat':(out/'COMPAT.json.gz').write_bytes(b'changed')
    elif change=='review':(out/'REVIEW.json.gz').write_bytes(b'changed')
    else:(packet/'syntax-witnesses/native/execution.json').unlink()
    execution.write_text(json.dumps(record));assert verify_capture(packet,ROOT)
