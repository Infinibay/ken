"""The added host binds original, native, resource and source records together."""
from copy import deepcopy
from pathlib import Path
import gzip,json,os,platform,shutil,subprocess
import pytest
from tools.rust_migration.native_json import identity
ROOT=Path(__file__).resolve().parents[2]

def test_new_x86_reference_is_bounded_and_keeps_the_actual_platform():
    from tools.rust_migration.grammar_extension import read_reference
    value=read_reference(ROOT/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz')
    assert len(value['cases'])==215 and len(value['discovered'])==124
    assert(value['runtime']['system'],value['runtime']['machine'],value['runtime']['python'])==('Linux','x86_64','3.12.9')

def test_corrupt_compressed_reference_does_not_become_an_empty_oracle(tmp_path):
    from tools.rust_migration.grammar_extension import read_reference
    path=tmp_path/'ref.json.gz';path.write_bytes(b'corrupt')
    with pytest.raises((ValueError,OSError,EOFError)):read_reference(path)

@pytest.fixture
def packet(tmp_path):
    configured=os.environ.get('KEN_GRAMMAR_EXTENSION_PACKET')
    if configured:
        target=tmp_path/'packet';shutil.copytree(configured,target);return target
    target=tmp_path/'packet';target.mkdir()
    shutil.copytree(ROOT/'.ken/rust-migration/m4d-x86-grammar/native-compatibility',target/'native')
    shutil.copytree(ROOT/'.ken/rust-migration/m4d-x86-grammar/original-x86',target/'original')
    shutil.copyfile(ROOT/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz',target/'reference.json.gz')
    (target/'bin').mkdir();shutil.copyfile(ROOT/'target/debug/examples/parser_probe',target/'bin/parser-probe')
    source=json.loads((target/'native/BUILD.json').read_bytes())['sources']
    (target/'SOURCES.json').write_text(json.dumps(source))
    host=dict(format='ken-grammar-host/1',platform='linux-x86_64',system=platform.system(),machine=platform.machine(),python=platform.python_version(),rustc='rustc 1.95.0 (prepared local toolchain)',commit='local-uncommitted')
    (target/'HOST.json').write_text(json.dumps(host));return target

def test_actual_added_host_capture_authenticates_complete_source_and_oracle(packet):
    from tools.rust_migration.grammar_extension import verify_grammar_capture
    assert not verify_grammar_capture(packet,ROOT)

@pytest.mark.parametrize('change',['host','source','binary','binary-architecture','reference','raw','raw-type','input','missing','original','runtime'])
def test_resealed_or_changed_added_host_capture_rejects(packet,change):
    from tools.rust_migration.grammar_extension import verify_grammar_capture
    assert not verify_grammar_capture(packet,ROOT)
    if change=='host':
        path=packet/'HOST.json';value=json.loads(path.read_bytes());value['platform']='linux-x86_64'if value['platform']=='linux-aarch64'else'linux-aarch64';path.write_text(json.dumps(value))
    elif change=='source':
        path=packet/'SOURCES.json';value=json.loads(path.read_bytes());value.pop(next(iter(value)));path.write_text(json.dumps(value))
    elif change=='binary':(packet/'bin/parser-probe').write_bytes(b'changed')
    elif change=='binary-architecture':
        path=packet/'bin/parser-probe';data=bytearray(path.read_bytes())
        if data[:4]==b'\x7fELF':data[18:20]=b'\x00\x00'
        else:data[4:8]=b'\x00'*4
        path.write_bytes(data)
        for name in ('execution','BUILD'):
            path=packet/'native'/(name+'.json');value=json.loads(path.read_bytes());value['native_sha256']=identity(packet/'bin/parser-probe')['sha256'];path.write_text(json.dumps(value))
    elif change in('reference','runtime'):
        path=packet/'reference.json.gz';value=json.loads(gzip.decompress(path.read_bytes()))
        reference=value.get('reference',value)
        if change=='reference':reference['cases'].pop()
        else:reference['runtime']['machine']='unrelated'
        path.write_bytes(gzip.compress(json.dumps(value).encode(),mtime=0))
    elif change=='raw':
        path=packet/'native/stdout.json';value=json.loads(path.read_bytes());value['cases'][0]['syntax'].pop();path.write_text(json.dumps(value))
    elif change=='raw-type':
        path=packet/'native/stdout.json';value=json.loads(path.read_bytes());value['cases'][0]['syntax'][0][1]=int(value['cases'][0]['syntax'][0][1]);path.write_text(json.dumps(value))
    elif change=='input':
        path=packet/'native/inputs.json';value=json.loads(path.read_bytes());value['cases'][0]['expected']={};path.write_text(json.dumps(value))
    elif change=='missing':(packet/'native/stderr.log').unlink()
    else:(packet/'original/original-observations.json').write_text('{}')
    assert verify_grammar_capture(packet,ROOT)

def test_fabricated_matrix_flag_cannot_replace_three_actual_hosts(tmp_path):
    from tools.rust_migration.grammar_extension import aggregate_grammar_hosts
    (tmp_path/'INDEX.json').write_text(json.dumps(dict(Grammar_x86_64_accepted=True)))
    result=aggregate_grammar_hosts(tmp_path,ROOT)
    assert not result['Grammar_x86_64_accepted']and not result['M4_accepted']and not result['migration_complete']and result['errors']

def gate_sample(tmp_path):
    from tools.rust_migration.grammar_extension import RUST_COMMANDS,LINT_COMMANDS,TEST_FILES
    gate=tmp_path/'gates';gate.mkdir()
    configured=os.environ.get('KEN_GRAMMAR_EXTENSION_PACKET')
    source=Path(configured)/'gates'if configured else ROOT/'.ken/rust-migration/m4d-x86-grammar/local-gates'
    for name in RUST_COMMANDS:
        filename='rust-doc.log'if name=='doc-tests'and not configured else name+'.log'
        shutil.copyfile(source/filename,gate/(name+'.log'))
    (gate/'python-list.log').write_text('tests/rust_migration/test_grammar_extension.py::sample\n')
    (gate/'python-tests.log').write_text('1 passed\n')
    (gate/'python.xml').write_text('<testsuite><testcase classname="tests.rust_migration.test_grammar_extension" name="sample"/></testsuite>')
    commands={name:dict(command=command,exit=0,log=identity(gate/(name+'.log')))for name,command in RUST_COMMANDS.items()}
    for name,last in [('python-list','--collect-only'),('python-tests','--junitxml=/recorded/gates/python.xml')]:
        commands[name]=dict(command=['/recorded/.venv/bin/python','-m','pytest','-o','addopts=','-q',*TEST_FILES,last],exit=0,log=identity(gate/(name+'.log')))
    (gate/'COMMANDS.json').write_text(json.dumps(commands))
    (gate/'fmt.log').write_text('');(gate/'clippy.log').write_text('    Finished `dev` profile [unoptimized] target(s) in 0.1s\n')
    (gate/'LINT.json').write_text(json.dumps({name:dict(command=command,exit=0,log=identity(gate/(name+'.log')))for name,command in LINT_COMMANDS.items()}))
    return gate

def test_complete_native_and_scoped_tooling_gate_receipts_match(tmp_path):
    from tools.rust_migration.grammar_extension import verify_grammar_gates
    assert not verify_grammar_gates(gate_sample(tmp_path),python_roots=1)

@pytest.mark.parametrize('change',['rust-missing','rust-filtered','doc-missing','python-missing','lint-empty','exit','command','hash'])
def test_missing_or_resealed_gate_records_do_not_accept(tmp_path,change):
    from tools.rust_migration.grammar_extension import verify_grammar_gates
    gate=gate_sample(tmp_path);commands=json.loads((gate/'COMMANDS.json').read_bytes())
    if change=='rust-missing':
        path=gate/'rust-tests.log';text=path.read_text();line=next(line for line in text.splitlines(True)if line.startswith('test ')and' ... ok'in line);path.write_text(text.replace(line,'',1));commands['rust-tests']['log']=identity(path)
    elif change=='rust-filtered':
        path=gate/'rust-tests.log';path.write_text(path.read_text().replace('0 filtered out','1 filtered out',1));commands['rust-tests']['log']=identity(path)
    elif change=='doc-missing':(gate/'doc-tests.log').unlink()
    elif change=='python-missing':(gate/'python.xml').write_text('<testsuite/>')
    elif change=='lint-empty':
        (gate/'clippy.log').write_text('');record=json.loads((gate/'LINT.json').read_bytes());record['clippy']['log']=identity(gate/'clippy.log');(gate/'LINT.json').write_text(json.dumps(record))
    elif change=='exit':commands['rust-tests']['exit']=1
    elif change=='command':commands['rust-tests']['command'].append('--lib')
    else:(gate/'python-tests.log').write_text('fabricated')
    (gate/'COMMANDS.json').write_text(json.dumps(commands))
    assert verify_grammar_gates(gate,python_roots=1)

def test_original_fixture_transport_restores_the_exact_capture_without_rerunning_it(tmp_path):
    from tools.rust_migration.grammar_extension import restore_fixture_original,read_reference
    path=ROOT/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz';target=tmp_path/'original'
    reference=restore_fixture_original(path,target)
    assert reference==read_reference(path)==json.loads((target/'reference.json').read_bytes())
    before={name:identity(target/name)for name in ('reference.json','request.json','stdout.log','stderr.log','original-observations.json','original-tests.xml')}
    assert restore_fixture_original(path,target)==reference
    assert before=={name:identity(target/name)for name in before}

def test_original_fixture_transport_cannot_write_an_unowned_member(tmp_path):
    from tools.rust_migration.grammar_extension import restore_fixture_original
    source=ROOT/'crates/ken-syntax/tests/fixtures/reference-linux-x86_64.json.gz'
    value=json.loads(gzip.decompress(source.read_bytes()));value['files']['../outside']=next(iter(value['files'].values()))
    path=tmp_path/'changed.json.gz';path.write_bytes(gzip.compress(json.dumps(value).encode(),mtime=0))
    outside=tmp_path/'outside';outside.write_bytes(b'unchanged');target=tmp_path/'original'
    with pytest.raises(ValueError):restore_fixture_original(path,target)
    assert outside.read_bytes()==b'unchanged'and not target.exists()

def test_archived_grammar_sources_replay_without_the_live_checkout(packet,tmp_path):
    from tools.rust_migration.grammar_packet import snapshot_packet
    from tools.rust_migration.grammar_extension import extract_grammar_snapshot,verify_grammar_capture
    snapshot_packet(ROOT,packet)
    snapshot=tmp_path/'snapshot';extract_grammar_snapshot(packet,snapshot)
    assert not verify_grammar_capture(packet,snapshot)

@pytest.mark.parametrize('change',['none','missing-tooling','missing-inventory','missing-archive','changed-validator','cross-host-tooling','archive-bytes'])
def test_finalized_packet_requires_the_complete_current_tooling_archive(packet,tmp_path,change):
    from tools.rust_migration.grammar_packet import snapshot_packet
    from tools.rust_migration.grammar_extension import verify_grammar_snapshot,extract_grammar_snapshot
    snapshot_packet(ROOT,packet)
    assert not verify_grammar_snapshot(packet,ROOT)
    repo=ROOT
    if change=='missing-tooling':(packet/'VALIDATION-SOURCES.json').unlink()
    elif change=='missing-inventory':(packet/'SNAPSHOT.json').unlink()
    elif change=='missing-archive':(packet/'source-snapshot.tar.gz').unlink()
    elif change=='changed-validator':
        repo=tmp_path/'snapshot';extract_grammar_snapshot(packet,repo)
        path=repo/'tools/rust_migration/grammar_extension.py';path.write_bytes(path.read_bytes()+b'\n# changed without collecting different node IDs\n')
    elif change=='cross-host-tooling':
        path=packet/'VALIDATION-SOURCES.json';value=json.loads(path.read_bytes());value['tools/rust_migration/grammar_extension.py']['sha256']='0'*64;path.write_text(json.dumps(value))
    elif change=='archive-bytes':(packet/'source-snapshot.tar.gz').write_bytes(b'changed archive')
    errors=verify_grammar_snapshot(packet,repo)
    assert bool(errors)==(change!='none')

def test_review_is_bound_to_both_native_sources_and_complete_tooling(tmp_path):
    from tools.rust_migration.grammar_extension import verify_grammar_review
    source={'Cargo.toml':dict(bytes=1,sha256='a'*64)};tooling={'tools/rust_migration/grammar_extension.py':dict(bytes=1,sha256='b'*64)}
    raw=tmp_path/'REVIEW.md';raw.write_text('One whole-plan test review; no open blocking findings.\n')
    record=dict(format='ken-grammar-extension-review/1',whole_plan=True,reviewer='test-review',critical_open=[],important_open=[],accepted_sources=source,accepted_tooling=tooling,raw_review=dict(path=raw.name,identity=identity(raw)))
    path=tmp_path/'REVIEW.json';path.write_text(json.dumps(record))
    assert not verify_grammar_review(path,source,tooling)
    record=json.loads(path.read_bytes());record['accepted_tooling']['tools/rust_migration/grammar_extension.py']['sha256']='c'*64;path.write_text(json.dumps(record))
    assert verify_grammar_review(path,source,tooling)
