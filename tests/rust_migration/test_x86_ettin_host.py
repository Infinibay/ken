"""The x86 Ettin executor consumes the existing original and exact audit scope."""
from pathlib import Path
import json,os,shutil
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_ettin_original_requires_exact_x86_host_and_preserved_cases():
    from tools.rust_migration.ettin_host import host_original
    from tools.rust_migration.ettin_reference import ettin_cases
    original,path=host_original(ROOT,'Linux','x86_64')
    assert original['cases']==ettin_cases()and len(original['results'])==23
    assert path==ROOT/'crates/ken-models/tests/fixtures/ettin/linux-x86_64-original.json'
    for system,machine in [('Linux','aarch64'),('Darwin','arm64'),('Windows','x86_64')]:
        with pytest.raises(ValueError):host_original(ROOT,system,machine)

def test_missing_ettin_capture_rejects_passing_summary(tmp_path):
    from tools.rust_migration.ettin_host import verify_ettin_capture
    (tmp_path/'summary.json').write_text('{"passed":true}')
    assert verify_ettin_capture(tmp_path,ROOT)

@pytest.fixture
def packet(tmp_path):
    configured=Path(os.environ.get('KEN_ETTIN_HOST_PACKET',ROOT/'.ken/rust-migration/x86-ettin-host/packet'))
    out=tmp_path/'packet';shutil.copytree(configured,out);return out

def test_actual_ettin_capture_matches_original_and_fresh_native_outputs(packet):
    from tools.rust_migration.ettin_host import verify_ettin_capture
    assert not verify_ettin_capture(packet,ROOT)

@pytest.mark.parametrize('change',['host','original','input-answer','vector','binary','audit','source','generated','missing-output','extra-output','parent'])
def test_resealed_ettin_capture_rejects(packet,change):
    from tools.rust_migration.ettin_host import verify_ettin_capture
    from tools.rust_migration.native_json import identity
    assert not verify_ettin_capture(packet,ROOT)
    out=packet/'ettin';capture=out/'native';execution=capture/'execution.json'
    record=json.loads(execution.read_bytes())
    if change=='host':
        path=packet/'HOST.json';value=json.loads(path.read_bytes());value.update(machine='aarch64',arch='aarch64');path.write_text(json.dumps(value))
    elif change=='original':(out/'ORIGINAL.json').write_text('{}')
    elif change=='binary':(out/'bin/ettin_probe').write_bytes(b'changed')
    elif change=='parent':(packet/'SDK.json').unlink()
    elif change in('input-answer','vector'):
        filename,key=('inputs.json','request_sha256')if change=='input-answer'else('stdout.json','stdout_sha256')
        path=capture/filename;value=json.loads(path.read_bytes())
        if change=='input-answer':value['expected']={}
        else:value['results'][1]['calls'][1]['scores'][0]+=1.
        path.write_text(json.dumps(value));record[key]=identity(path)['sha256']
    elif change=='audit':record['command']=['/usr/bin/python',record['command'][-1]]
    elif change=='source':
        name=next(name for name in record['owned_before']if name.startswith('source/'))
        record['owned_before'][name]['sha256']='a'*64;record['owned_after'][name]['sha256']='a'*64
    elif change=='generated':record['generated_files']['prepared/model.onnx']['sha256']='a'*64
    elif change=='missing-output':del record['owned_after']['prepared/model.onnx']
    elif change=='extra-output':record['owned_after']['prepared/foreign']={'bytes':1,'sha256':'a'*64}
    execution.write_text(json.dumps(record))
    assert verify_ettin_capture(packet,ROOT)

def test_missing_ettin_gates_reject(tmp_path):
    from tools.rust_migration.ettin_host import verify_ettin_gates
    assert verify_ettin_gates(tmp_path)

def test_ettin_junit_must_match_recorded_destination(tmp_path,monkeypatch):
    from tools.rust_migration import ettin_host as module
    out=tmp_path/'ettin';gates=out/'gates';gates.mkdir(parents=True)
    nodes=[module.TEST_FILES[0]+'::case_'+str(i)for i in range(module.PYTHON_ROOTS)]
    states={node.replace(module.TEST_FILES[0],module.TEST_FILES[0][:-3].replace('/','.')):'passed'for node in nodes}
    (gates/'python-list.log').write_text('\n'.join(nodes)+'\n')
    (gates/'ettin-list.log').write_text('\n'.join('unit_'+str(i)+': test'for i in range(16))+'\n')
    (gates/'ettin-tests.log').write_text('synthetic destination test\n')
    monkeypatch.setattr(module,'command_gate_errors',lambda *a,**kw:[])
    monkeypatch.setattr(module,'rust_gate_errors',lambda *a:[])
    monkeypatch.setattr(module,'junit_states',lambda *a:states)
    commands=module.python_commands('/usr/bin/python',out.resolve())
    records={name:{'command':argv}for name,argv in commands.items()}
    (out/'PYTHON-OUTPUT.json').write_text(json.dumps(dict(format='ken-ettin-python-output/1',recorded_directory=str(out.resolve()))))
    path=gates/'PYTHON.json';path.write_text(json.dumps(records))
    assert not module.verify_ettin_gates(out)
    for crossed in('/tmp/unrelated.xml','/tmp/python.xml'):
        records['python-tests']['command'][-1]='--junitxml='+crossed;path.write_text(json.dumps(records))
        assert module.verify_ettin_gates(out)
