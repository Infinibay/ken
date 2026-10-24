"""Raw process evidence remains bound after apparent checksum resealing."""
from pathlib import Path
from copy import deepcopy
import gzip,json,os,shutil
import pytest
from tools.rust_migration.native_json import identity,load
from tools.rust_migration.piece_evidence import verify_capture
ROOT=Path(__file__).resolve().parents[2]
@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_PIECE_NATIVE_DIR',ROOT/'.superpowers/sdd/2026-10-23-rust-source-pieces/native-x86-probe-audit'))/'cards'
    assert source.is_dir(),'run the actual source-piece native captures before evidence gates'
    destination=tmp_path/'capture';shutil.copytree(source,destination)
    ref=Path(os.environ['KEN_PIECE_REFERENCE_DIR'])/'piece-reference-cards.json'if'KEN_PIECE_REFERENCE_DIR'in os.environ else ROOT/'crates/ken-retrieval/tests/fixtures/piece-reference-cards-linux-x86_64.json.gz'
    reference=json.loads(gzip.decompress(ref.read_bytes())if ref.suffix=='.gz'else ref.read_bytes())
    return destination,reference
def test_actual_input_only_capture_and_loader_audit_verify(packet):
    out,reference=packet;assert not verify_capture(out,reference,repo=ROOT)
@pytest.mark.parametrize('change',['raw','resealed-source','input-answer','missing','schema','platform','source-map','binary','extra','scope','exec','resource'])
def test_resealed_or_incomplete_native_evidence_rejects(packet,change):
    out,reference=packet;execution=load(out/'execution.json')
    if change in('raw','resealed-source','schema','platform','extra','scope'):
        value=load(out/'stdout.json')
        if change in('raw','resealed-source'):value['cases'][0]['result']['cards'][0]['excerpts'][0]['content']+=' fabricated'
        elif change=='schema':value['cases'].pop()
        elif change=='platform':value['machine']='wrong'
        elif change=='extra':value['passed']=True
        else:value['metrics']['scope']='public end-to-end search'
        (out/'stdout.json').write_text(json.dumps(value)+'\n')
        if change!='raw':execution['stdout_sha256']=identity(out/'stdout.json')['sha256']
    elif change=='input-answer':
        value=load(out/'inputs.json');value['cases'][0]['result']={};(out/'inputs.json').write_text(json.dumps(value)+'\n');execution['request_sha256']=identity(out/'inputs.json')['sha256']
    elif change=='missing':(out/'stderr.log').unlink()
    elif change=='source-map':
        value=load(out/'SOURCES.json');value.pop(next(iter(value)));(out/'SOURCES.json').write_text(json.dumps(value)+'\n')
    elif change=='binary':execution['native_sha256']='0'*64
    elif change=='exec':
        if execution['system']=='linux':(out/'exec.trace').write_text('execve("python", [], []) = 0\nconnect(1, {}, 0) = 0\n')
        else:(out/'stderr.log').write_text('libpython3.12.dylib\n')
    else:execution['owned_before']['static.npz']['sha256']='0'*64;execution['owned_after']=deepcopy(execution['owned_before'])
    (out/'execution.json').write_text(json.dumps(execution)+'\n')
    assert verify_capture(out,reference,repo=ROOT)
def snapshot_packet(tmp_path):
    import hashlib,io,tarfile
    from tools.rust_migration.piece_evidence import PREDECESSOR
    packet=tmp_path/'packet';packet.mkdir()
    payloads={'Cargo.toml':b'fixture manifest\n','Cargo.lock':b'fixture lock\n','rust-toolchain.toml':b'fixture toolchain\n','tools/rust_migration/scope.py':b'# frozen validation scope\n',PREDECESSOR['path']+'/FILES.json':(ROOT/PREDECESSOR['path']/'FILES.json').read_bytes()}
    records={name:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())for name,raw in payloads.items()}
    (packet/'SNAPSHOT.json').write_text(json.dumps(records))
    (packet/'SOURCES.json').write_text(json.dumps({name:records[name]for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml')}))
    (packet/'VALIDATION-SOURCES.json').write_text(json.dumps({'tools/rust_migration/scope.py':records['tools/rust_migration/scope.py']}))
    def archive(extra=None,duplicate=False,symlink=False,corrupt=False):
        with tarfile.open(packet/'source-snapshot.tar.gz','w:gz')as output:
            for name,raw in payloads.items():
                info=tarfile.TarInfo(name);info.size=len(raw);output.addfile(info,io.BytesIO(b'x'*len(raw)if corrupt else raw))
                if duplicate:output.addfile(info,io.BytesIO(raw));duplicate=False
            if extra:
                info=tarfile.TarInfo(extra);info.size=0
                if symlink:info.type=tarfile.SYMTYPE;info.linkname='../../outside'
                output.addfile(info,io.BytesIO())
    archive();return packet,payloads,archive

def test_archived_sources_extract_and_authenticate_before_replay(tmp_path):
    from tools.rust_migration.piece_evidence import extract_snapshot
    packet,payloads,_=snapshot_packet(tmp_path);destination=tmp_path/'snapshot'
    assert extract_snapshot(packet,destination)==destination
    assert all((destination/name).read_bytes()==raw for name,raw in payloads.items())
@pytest.mark.parametrize('change',['parent','absolute','symlink','duplicate','corrupt','existing'])
def test_unsafe_or_changed_source_archives_never_escape_or_overwrite(tmp_path,change):
    from tools.rust_migration.piece_evidence import extract_snapshot
    packet,_,archive=snapshot_packet(tmp_path);destination=tmp_path/'snapshot';outside=tmp_path/'outside';outside.write_bytes(b'unchanged')
    if change=='parent':archive(extra='../outside')
    elif change=='absolute':archive(extra=str(outside))
    elif change=='symlink':archive(extra='link',symlink=True)
    elif change=='duplicate':archive(duplicate=True)
    elif change=='corrupt':archive(corrupt=True)
    else:destination.mkdir();(destination/'keep').write_bytes(b'keep')
    with pytest.raises((ValueError,OSError)):extract_snapshot(packet,destination)
    assert outside.read_bytes()==b'unchanged'
    if change=='existing':assert(destination/'keep').read_bytes()==b'keep'

def test_actual_complete_native_discovery_excludes_nested_health_harness():
    import platform,re
    from tools.rust_migration.integration_validate import rust_gate_errors
    from tools.rust_migration.piece_evidence import NATIVE_ROOTS
    native=Path(os.environ.get('KEN_PIECE_NATIVE_DIR',ROOT/'.superpowers/sdd/2026-10-23-rust-source-pieces/native-x86-probe-audit'))
    gates=native.parent/'gates'
    listed=(gates/'rust-list.log').read_text();output=(gates/'rust-tests.log').read_text()
    assert not rust_gate_errors(listed,output)
    discovered=len(re.findall(r'^([^\n]+): test$',listed,re.M))
    assert discovered==NATIVE_ROOTS[platform.system()]
    # The health suite reexecutes one root in its own filtered child harness.
    raw_passed=sum(map(int,re.findall(r'test result: ok\. (\d+) passed',output)))
    assert raw_passed==discovered+1

def lint_gate_sample(tmp_path):
    from tools.rust_migration.native_json import identity
    gate=tmp_path/'gates';gate.mkdir()
    (gate/'rust-list.log').write_text('parent: test\n')
    (gate/'rust-tests.log').write_text('test parent ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n')
    (gate/'python-list.log').write_text('tests/rust_migration/test_piece_probe.py::sample\n')
    (gate/'python.xml').write_text('<testsuite><testcase classname="tests.rust_migration.test_piece_probe" name="sample"/></testsuite>')
    (gate/'fmt.log').write_bytes(b'')
    (gate/'clippy.log').write_text('    Checking ken-retrieval v0.18.0\n    Finished `dev` profile [unoptimized] target(s) in 0.5s\n')
    commands={'fmt':['cargo','fmt','--all','--check'],'clippy':['cargo','clippy','--locked','--offline','-p','ken-core','-p','ken-retrieval','--all-targets','--','-D','warnings']}
    (gate/'LINT.json').write_text(json.dumps({name:dict(command=command,exit=0,log=identity(gate/(name+'.log')))for name,command in commands.items()}))
    return gate

def test_complete_lint_receipt_has_actual_success_and_finished_output(tmp_path):
    from tools.rust_migration.piece_evidence import verify_gates
    assert not verify_gates(lint_gate_sample(tmp_path),rust_roots=1,python_roots=1)

@pytest.mark.parametrize('change',['empty','truncated','exit','command','hash','missing'])
def test_incomplete_or_resealed_lint_cannot_certify_gates(tmp_path,change):
    from tools.rust_migration.native_json import identity
    from tools.rust_migration.piece_evidence import verify_gates
    gate=lint_gate_sample(tmp_path);record=load(gate/'LINT.json')
    if change in('empty','truncated'):
        (gate/'clippy.log').write_text(''if change=='empty'else '    Checking ken-retrieval v0.18.0\n')
        record['clippy']['log']=identity(gate/'clippy.log')
    elif change=='exit':record['clippy']['exit']=1
    elif change=='command':record['clippy']['command'].remove('--all-targets')
    elif change=='hash':(gate/'clippy.log').write_text('    Finished `dev` profile [unoptimized] target(s) in 0.6s\n')
    else:record['fmt'].pop('exit')
    (gate/'LINT.json').write_text(json.dumps(record))
    assert verify_gates(gate,rust_roots=1,python_roots=1)
