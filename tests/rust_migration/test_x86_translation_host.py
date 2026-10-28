"""Reject incomplete or altered native-only translation evidence."""
from pathlib import Path
import json, os, shutil
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_absent_host_cannot_be_treated_as_accepted(tmp_path):
    from tools.rust_migration.x86_translation_host import verify_capture
    assert verify_capture(tmp_path,ROOT)

def test_request_contains_only_registered_inputs_and_physical_resources(tmp_path):
    from tools.rust_migration.x86_translation_host import request_for
    from tools.rust_migration.x86_translation_reference import load
    request=request_for(load(ROOT),tmp_path,{'bytes':1,'sha256':'0'*64},ROOT)
    assert set(request)=={'registration','source','cache','cases','native_runtime'}
    assert 'results'not in request and len(request['cases'])==29
    assert Path(request['native_runtime']['module_path']).parent==tmp_path/'runtime'

def packet():
    return Path(os.environ['KEN_X86_TRANSLATION_PACKET'])

def test_actual_confined_native_histories_match_all_29_originals():
    from tools.rust_migration.x86_translation_host import verify_capture
    assert not verify_capture(packet(),ROOT)

@pytest.mark.parametrize('member', ['SOURCES.json','BACKEND-BUILD.json','SDK.json','bin/translation_probe',
    'bin/libken_ct2_backend.so','native/inputs.json','native/stdout.json','native/execution.json'])
def test_changed_source_build_binary_request_or_observation_is_rejected(tmp_path,member):
    from tools.rust_migration.x86_translation_host import verify_capture
    target=tmp_path/'packet';shutil.copytree(packet(),target)
    path=target/member
    if path.suffix=='.json':
        value=json.loads(path.read_bytes())
        if member=='native/stdout.json':value['results'].pop()
        elif member=='native/inputs.json':value['expected_outputs']=['precomputed']
        else:value.clear()
        path.write_text(json.dumps(value))
    else:path.write_bytes(b'changed executable')
    assert verify_capture(target,ROOT),member
