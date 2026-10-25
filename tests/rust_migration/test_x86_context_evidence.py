"""Contextual capability must retain its original host and real native audit."""
from pathlib import Path
import json,os,shutil
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_context_original_is_bound_to_exact_host_and_fixed_cases():
    from tools.rust_migration.context_host import host_original
    original,_=host_original(ROOT,'Linux','x86_64')
    assert(original['platform'],original['architecture'])==('Linux','x86_64')
    assert len(original['cases'])==len(original['results'])==20
    with pytest.raises(ValueError):host_original(ROOT,'Darwin','x86_64')


def test_missing_context_capture_cannot_be_replaced_by_a_summary(tmp_path):
    from tools.rust_migration.context_host import verify_context_capture
    (tmp_path/'summary.json').write_text('{"passed":true}')
    assert verify_context_capture(tmp_path,ROOT)

@pytest.fixture
def packet(tmp_path):
    configured=Path(os.environ.get('KEN_CONTEXT_HOST_PACKET',ROOT/'.ken/rust-migration/x86-context/packet-permanent'))
    out=tmp_path/'packet';shutil.copytree(configured,out);return out


def test_actual_context_capture_uses_original_vectors_and_complete_native_audit(packet):
    from tools.rust_migration.context_host import verify_context_capture
    assert not verify_context_capture(packet,ROOT)

@pytest.mark.parametrize('change',['original','input-answer','vector','binary','audit','owned'])
def test_changed_or_resealed_context_capture_rejects(packet,change):
    from tools.rust_migration.context_host import verify_context_capture
    from tools.rust_migration.native_json import identity
    assert not verify_context_capture(packet,ROOT)
    out=packet/'context';capture=out/'native'
    if change=='original':(out/'ORIGINAL.json').write_text('{}')
    elif change=='binary':(out/'bin/context_probe').write_bytes(b'changed')
    elif change=='audit':
        path=capture/'execution.json';value=json.loads(path.read_bytes());value['command']=['/usr/bin/python',value['command'][-1]];path.write_text(json.dumps(value))
    elif change=='owned':
        path=capture/'execution.json';value=json.loads(path.read_bytes());value['owned_before']['foreign']={'bytes':1,'sha256':'a'*64};value['owned_after']=value['owned_before'];path.write_text(json.dumps(value))
    else:
        filename,key=('inputs.json','request_sha256')if change=='input-answer'else('stdout.json','stdout_sha256')
        path=capture/filename;value=json.loads(path.read_bytes())
        if change=='input-answer':value['expected']={}
        else:value['results'][-1]['calls'][-1][0][0]+=1.0
        path.write_text(json.dumps(value));execution=capture/'execution.json';record=json.loads(execution.read_bytes());record[key]=identity(path)['sha256'];execution.write_text(json.dumps(record))
    assert verify_context_capture(packet,ROOT)


def test_context_snapshot_requires_registration_original_and_design(tmp_path):
    from tools.rust_migration.context_host import verify_context_support
    assert verify_context_support(tmp_path,ROOT)
