"""Execution-profile packets select originals before answers and replay without local detection."""
from pathlib import Path
import json,os
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_recorded_remote_profile_replays_without_detecting_this_cpu(tmp_path):
    from tools.rust_migration.execution_host import record_profiles,recorded_reference
    from tools.rust_migration.native_json import load
    from tools.rust_migration.execution_registry import INDEX
    registry=load(ROOT/INDEX);context=registry['families']['context'][-1];alignment=registry['families']['alignment'][0]
    caps=dict(format='ken-x86-capabilities/1',target='linux-x86_64',features=context['descriptor']['features'])
    record_profiles(ROOT,tmp_path,caps,alignment['descriptor'])
    entry,oracle=recorded_reference(ROOT,tmp_path,'context')
    assert entry['id']==context['id']
    assert len(oracle['cases'])==20
    from tools.rust_migration.context_host import host_original
    selected,path=host_original(ROOT,'Linux','x86_64',profile=entry['descriptor'])
    assert selected==oracle and path==ROOT/entry['reference']['path']
    with pytest.raises(ValueError):record_profiles(ROOT,tmp_path,caps,alignment['descriptor'])

@pytest.mark.parametrize('change',['unknown','id','reference','capabilities','threads'])
def test_changed_profile_packet_cannot_select_a_reference(tmp_path,change):
    from tools.rust_migration.execution_host import record_profiles,recorded_reference
    from tools.rust_migration.native_json import load
    from tools.rust_migration.execution_registry import INDEX
    registry=load(ROOT/INDEX);context=registry['families']['context'][0];alignment=registry['families']['alignment'][0]
    caps=dict(format='ken-x86-capabilities/1',target='linux-x86_64',features=context['descriptor']['features'])
    record_profiles(ROOT,tmp_path,caps,alignment['descriptor'])
    path=tmp_path/'EXECUTION-PROFILES.json';record=load(path)
    if change=='unknown':record['descriptors']['context']['features']['unknown']=True
    elif change=='id':record['references']['context']['id']='0'*64
    elif change=='reference':record['references']['context']['reference']['sha256']='0'*64
    elif change=='capabilities':record['capabilities']['features']['avx2']=False
    else:record['descriptors']['alignment']['threads']=2
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):recorded_reference(ROOT,tmp_path,'context')

def test_detected_profile_uses_effective_cpu_and_actual_pinned_blas(tmp_path):
    from tools.rust_migration.execution_host import detect_profiles,record_profiles,recorded_reference
    probe=Path(os.environ.get('KEN_X86_FEATURES_PROBE',ROOT/'.ken/rust-migration/execution-profiles/x86-features-probe'))
    caps,alignment=detect_profiles(probe)
    record_profiles(ROOT,tmp_path,caps,alignment)
    assert len(recorded_reference(ROOT,tmp_path,'alignment')[1]['cases'])==245

def test_new_x86_context_requires_a_profile_packet(tmp_path):
    from tools.rust_migration.execution_host import recorded_reference
    with pytest.raises((OSError,ValueError)):recorded_reference(ROOT,tmp_path,'context')

def test_rejected_unknown_profile_retains_detection_before_selection(tmp_path):
    from tools.rust_migration.execution_host import prepare_host
    from tools.rust_migration.execution_registry import INDEX
    from tools.rust_migration.native_json import load,identity
    context=load(ROOT/INDEX)['families']['context'][0]['descriptor']
    caps=dict(format='ken-x86-capabilities/1',target='linux-x86_64',features=context['features']|dict(hybrid=True))
    probe=tmp_path/'synthetic-capability-fixture';probe.write_text('#!/usr/bin/env python3\nprint('+repr(json.dumps(caps))+')\n');probe.chmod(0o755)
    packet=tmp_path/'packet';packet.mkdir()
    with pytest.raises(ValueError):prepare_host(ROOT,packet,probe)
    retained=load(packet/'DETECTED-PROFILES.json')
    assert retained['capabilities']==caps and retained['probe']==identity(probe)
    assert retained['alignment']['threads']==1
    assert not(packet/'EXECUTION-PROFILES.json').exists()


def test_changed_native_runtime_registration_rejects_stale_profile(tmp_path):
    from tools.rust_migration.execution_profiles import descriptors
    from tools.rust_migration.execution_registry import INDEX
    from tools.rust_migration.native_json import load
    index=load(ROOT/INDEX);context=index['families']['context'][0]['descriptor'];alignment=index['families']['alignment'][0]['descriptor']
    caps=dict(format='ken-x86-capabilities/1',target='linux-x86_64',features=context['features'])
    name='crates/ken-models/resources/onnx-runtime-libraries.json';registration=load(ROOT/name)
    next(r for r in registration['libraries']if(r['os'],r['arch'])==('linux','x86_64'))['sha256']='0'*64
    path=tmp_path/name;path.parent.mkdir(parents=True);path.write_text(json.dumps(registration))
    with pytest.raises(ValueError):descriptors(caps,{key:alignment[key]for key in('core','threads','sha256')},tmp_path)
