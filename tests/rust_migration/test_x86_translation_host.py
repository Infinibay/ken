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

def test_selected_cargo_probe_comes_from_supplied_checkout_and_explicit_target(tmp_path):
    from tools.rust_migration.x86_translation_host import probe_artifact
    repo=tmp_path/'checkout';target=tmp_path/'explicit-target';binary=target/'debug/examples/translation_probe'
    row=dict(reason='compiler-artifact',manifest_path=str(repo/'crates/ken-models/Cargo.toml'),
        target=dict(name='translation_probe',kind=['example'],crate_types=['bin'],src_path=str(repo/'crates/ken-models/examples/translation_probe.rs')),
        executable=str(binary))
    log=tmp_path/'cargo.log'
    def save(rows):log.write_text('\n'.join(json.dumps(v)for v in rows)+'\n')
    finish=dict(reason='build-finished',success=True)
    save([row,finish]);assert probe_artifact(log,repo,target)==binary
    for changes in ({'manifest_path':str(tmp_path/'other/Cargo.toml')},{'executable':str(tmp_path/'stale/translation_probe')}):
        save([row|changes,finish])
        with pytest.raises(ValueError):probe_artifact(log,repo,target)
    save([row,row,finish])
    with pytest.raises(ValueError):probe_artifact(log,repo,target)
    save([row,dict(reason='build-finished',success=False)])
    with pytest.raises(ValueError):probe_artifact(log,repo,target)

def packet():
    return Path(os.environ['KEN_X86_TRANSLATION_PACKET'])

def test_actual_confined_native_histories_match_all_29_originals():
    from tools.rust_migration.x86_translation_host import verify_capture
    host=json.loads((packet()/'HOST.json').read_bytes())
    probe=json.loads((packet()/'PROBE.json').read_bytes())
    assert Path(probe['path']).is_relative_to(Path(host['target']))
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

@pytest.mark.parametrize('change',['cache','compiler','link'])
def test_resealed_native_host_compiler_proof_cannot_contradict_its_registered_inputs(tmp_path,change):
    from tools.rust_migration.x86_translation_host import verify_capture
    from tools.rust_migration.native_json import identity
    target=tmp_path/'packet';shutil.copytree(packet(),target)
    report=json.loads((target/'BACKEND-BUILD.json').read_bytes())
    if change=='cache':
        member='build/CMakeCache.txt';before=(target/'backend-proof'/member).read_text()
        after=before.replace('CMAKE_BUILD_TYPE:STRING=Release','CMAKE_BUILD_TYPE:STRING=Debug')
    elif change=='compiler':
        member='build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake';before=(target/'backend-proof'/member).read_text()
        after=before.replace('set(CMAKE_CXX_COMPILER_ABI "ELF")','set(CMAKE_CXX_COMPILER_ABI "Foreign")')
    else:
        member='build/CMakeFiles/ken_ct2_backend.dir/link.txt';before=(target/'backend-proof'/member).read_text();after=before.replace('$ORIGIN','/foreign')
    assert before!=after
    path=target/'backend-proof'/member;path.write_text(after);report['proof_files'][member]=identity(path)
    (target/'BACKEND-BUILD.json').write_text(json.dumps(report))
    assert verify_capture(target,ROOT),change


def test_missing_intel_reference_stops_before_build_or_inference(tmp_path,monkeypatch):
    from tools.rust_migration import x86_translation_host as host
    original_read=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda self,*args,**kwargs: 'vendor_id : GenuineIntel\n'
        if str(self)=='/proc/cpuinfo' else original_read(self,*args,**kwargs))
    def forbidden(*args,**kwargs):
        pytest.fail('missing reference must stop before build/inference')
    monkeypatch.setattr(host,'run_command_gates',forbidden)
    with pytest.raises(ValueError,match='independent.*MKL'):
        host.run_host(ROOT,tmp_path/'out',tmp_path/'source',tmp_path/'sdk',tmp_path/'backend')
    assert not (tmp_path/'out').exists()


def test_cpu_preflight_selects_dnnl_original_and_rejects_ambiguous_vendors():
    from tools.rust_migration.x86_translation_host import host_reference
    vendor,backend,expected=host_reference(ROOT,'vendor_id : AuthenticAMD\nvendor_id : AuthenticAMD\n')
    assert (vendor,backend)==('AuthenticAMD','DNNL')and len(expected['results'])==29
    with pytest.raises(ValueError,match='one CPU vendor'):
        host_reference(ROOT,'vendor_id : AuthenticAMD\nvendor_id : GenuineIntel\n')
