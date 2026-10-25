"""Core acceptance needs real native loading and pinned input/resource identities."""
from pathlib import Path
import json,os,shutil
import pytest
ROOT=Path(__file__).resolve().parents[2]

@pytest.fixture
def packet(tmp_path):
    configured=os.environ.get('KEN_NATIVE_CORE_PACKET')
    if configured:
        out=tmp_path/'packet';shutil.copytree(configured,out);return out
    from tools.rust_migration.native_core_evidence import core_source_identity
    from tools.rust_migration.native_json import identity
    base=ROOT/'.ken/rust-migration/x86-runtime-cores';out=tmp_path/'packet';out.mkdir()
    shutil.copytree(base/'native-core-capture',out/'native');(out/'bin').mkdir()
    shutil.copyfile(ROOT/'target/debug/examples/native_core_probe',out/'bin/native_core_probe')
    module=base/'torch-target/debug/libken_torch_backend.so';shutil.copyfile(module,out/'bin/backend')
    (out/'MODULE.json').write_text(json.dumps(identity(module)))
    (out/'SOURCES.json').write_text(json.dumps(core_source_identity(ROOT)))
    return out

def test_actual_core_capture_checks_complete_native_loading_and_byte_identity(packet):
    from tools.rust_migration.native_core_evidence import verify_core_capture
    assert not verify_core_capture(packet,ROOT)

@pytest.mark.parametrize('change',['source','binary','module','architecture','runtime','input-answer','input-root','loader','missing','exec','resource'])
def test_changed_or_resealed_core_capture_never_passes(packet,change):
    from tools.rust_migration.native_core_evidence import verify_core_capture
    from tools.rust_migration.native_json import identity
    assert not verify_core_capture(packet,ROOT)
    if change=='source':
        path=packet/'SOURCES.json';value=json.loads(path.read_bytes());value.pop(next(iter(value)));path.write_text(json.dumps(value))
    elif change=='binary':(packet/'bin/native_core_probe').write_bytes(b'changed')
    elif change=='module':(packet/'bin/backend').write_bytes(b'changed')
    elif change in('architecture','runtime'):
        path=packet/'native/stdout.json';value=json.loads(path.read_bytes())
        if change=='architecture':value['arch']='aarch64'if value['arch']=='x86_64'else'x86_64'
        else:value['onnx']['api']=26
        path.write_text(json.dumps(value));execution=packet/'native/execution.json';record=json.loads(execution.read_bytes());record['stdout_sha256']=identity(path)['sha256'];execution.write_text(json.dumps(record))
    elif change in('input-answer','input-root'):
        path=packet/'native/inputs.json';value=json.loads(path.read_bytes())
        if change=='input-answer':value['expected']={}
        else:value['torch']['core_root']='/borrowed/runtime'
        path.write_text(json.dumps(value));execution=packet/'native/execution.json';record=json.loads(execution.read_bytes());record['request_sha256']=identity(path)['sha256'];execution.write_text(json.dumps(record))
    elif change=='loader':(packet/'native/stderr.log').write_text('libpython3.12.so\n')
    elif change=='missing':(packet/'native/stdout.json').unlink()
    elif change=='exec':
        path=packet/'native/execution.json';value=json.loads(path.read_bytes());value['command']=['/usr/bin/python',value['command'][-1]];path.write_text(json.dumps(value))
    else:
        path=packet/'native/execution.json';value=json.loads(path.read_bytes());value['owned_before']['torch/lib/foreign.so']={'bytes':4,'sha256':'a'*64};value['owned_after']=value['owned_before'];path.write_text(json.dumps(value))
    assert verify_core_capture(packet,ROOT)

def test_absent_complete_gates_cannot_be_replaced_by_a_summary(tmp_path):
    from tools.rust_migration.native_core_gates import verify_core_gates
    (tmp_path/'summary.json').write_text('{"passed":true}')
    assert verify_core_gates(tmp_path)

@pytest.mark.parametrize('change',['none','missing-tooling','missing-inventory','missing-archive','changed-validator','archive-bytes','cross-tooling'])
def test_final_core_snapshot_requires_complete_current_tooling(packet,tmp_path,change):
    from tools.rust_migration.native_core_packet import snapshot_packet
    from tools.rust_migration.native_core_evidence import verify_core_snapshot,extract_core_snapshot
    snapshot_packet(ROOT,packet);assert not verify_core_snapshot(packet,ROOT);repo=ROOT
    if change=='missing-tooling':(packet/'VALIDATION-SOURCES.json').unlink()
    elif change=='missing-inventory':(packet/'SNAPSHOT.json').unlink()
    elif change=='missing-archive':(packet/'source-snapshot.tar.gz').unlink()
    elif change=='changed-validator':
        repo=tmp_path/'archived';extract_core_snapshot(packet,repo)
        path=repo/'tools/rust_migration/native_core_evidence.py';path.write_bytes(path.read_bytes()+b'\n# changed validator with identical test IDs\n')
    elif change=='archive-bytes':(packet/'source-snapshot.tar.gz').write_bytes(b'corrupt')
    elif change=='cross-tooling':
        path=packet/'VALIDATION-SOURCES.json';value=json.loads(path.read_bytes());value.pop(next(iter(value)));path.write_text(json.dumps(value))
    assert bool(verify_core_snapshot(packet,repo))==(change!='none')

def test_whole_plan_core_review_binds_native_sources_and_tooling(tmp_path):
    from tools.rust_migration.native_core_evidence import verify_core_review
    from tools.rust_migration.native_json import identity
    raw=tmp_path/'review.md';raw.write_text('one whole-plan review\n');source={'source':{'bytes':1,'sha256':'a'*64}};tooling={'validator':{'bytes':1,'sha256':'b'*64}}
    record=dict(format='ken-native-cpu-core-review/1',whole_plan=True,reviewer='test-review',critical_open=[],important_open=[],accepted_sources=source,accepted_tooling=tooling,raw_review=dict(path=raw.name,identity=identity(raw)))
    path=tmp_path/'REVIEW.json';path.write_text(json.dumps(record));assert not verify_core_review(path,source,tooling)
    changed=json.loads(path.read_bytes());changed['accepted_tooling']={};path.write_text(json.dumps(changed));assert verify_core_review(path,source,tooling)

@pytest.mark.parametrize('change',['missing','permissive'])
def test_new_macos_core_requires_process_and_network_confinement(packet,change):
    from tools.rust_migration.native_json import identity,verify_native_json
    capture=packet/'native';path=capture/'execution.json';record=json.loads(path.read_bytes())
    record['system']='macos';record['machine']='arm64';root=Path(record['cwd'])
    record['command']=[str(root/'native-probe')];record['env'].pop('LD_DEBUG',None);record['env']['DYLD_PRINT_LIBRARIES']='1'
    (capture/'stderr.log').write_text('dyld[123]: native-probe\n')
    record['stderr_sha256']=identity(capture/'stderr.log')['sha256']
    if change=='permissive':record['command']=['/usr/bin/sandbox-exec','-p','(version 1)(allow default)',str(root/'native-probe')]
    path.write_text(json.dumps(record))
    assert verify_native_json(capture,'ken-native-cpu-cores-',macos_confinement=True)


def test_macos_confinement_requires_actual_denied_child_and_network_observations(packet,tmp_path):
    from tools.rust_migration.native_core_evidence import verify_core_confinement
    from tools.rust_migration.native_json import identity
    assert verify_core_confinement(tmp_path,('macos','aarch64'))
    if json.loads((packet/'native/execution.json').read_bytes())['system']=='macos':
        assert not verify_core_confinement(packet,('macos','aarch64'))
        path=packet/'confinement/stdout.json';original=json.loads(path.read_bytes())
        for key in('self_child_blocked','absolute_child_blocked','network_blocked'):
            path.write_text(json.dumps(original|{key:False}))
            execution=packet/'confinement/execution.json';record=json.loads(execution.read_bytes());record['stdout_sha256']=identity(path)['sha256'];execution.write_text(json.dumps(record))
            assert verify_core_confinement(packet,('macos','aarch64'))
