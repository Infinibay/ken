"""Public CLI/MCP packets bind actual executables, resources and process ancestry."""
from pathlib import Path
import copy,json,os
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_cargo_selects_only_the_declared_public_binary_or_integration_caller(tmp_path):
    from tools.rust_migration.command_gates import cargo_artifact
    repo=tmp_path/'checkout';target=tmp_path/'explicit-target';log=tmp_path/'cargo.jsonl'
    finish=dict(reason='build-finished',success=True)
    for name,kind,source,binary,pattern in (
        ('ken-rs','bin','src/main.rs','debug/ken-rs','ken-rs'),
        ('search_cli','test','tests/search_cli.rs','debug/deps/search_cli-1234567890abcdef',r'search_cli-[0-9a-f]{16}'),
    ):
        row=dict(reason='compiler-artifact',manifest_path=str(repo/'crates/ken-cli/Cargo.toml'),
            target=dict(name=name,kind=[kind],crate_types=['bin'],src_path=str(repo/'crates/ken-cli'/source)),
            executable=str(target/binary))
        def save(rows):log.write_text('\n'.join(json.dumps(v)for v in rows)+'\n')
        def select():return cargo_artifact(log,repo,target,package='ken-cli',name=name,kind=kind,source=source,binary_pattern=pattern)
        save([row,finish]);assert select()==target/binary
        altered=[]
        for key,value in [('manifest_path',str(repo/'foreign/Cargo.toml')),('executable',str(tmp_path/'stale'/Path(binary).name)),('executable','relative/ken-rs')]:
            changed=copy.deepcopy(row);changed[key]=value;altered.append(changed)
        for key,value in [('src_path',str(repo/'foreign/main.rs')),('kind',['example']),('crate_types',['rlib'])]:
            changed=copy.deepcopy(row);changed['target'][key]=value;altered.append(changed)
        for changed in altered:
            save([changed,finish])
            with pytest.raises(ValueError):select()
        for rows in ([row,row,finish],[row,dict(reason='build-finished',success=False)],[row],[]):
            save(rows)
            with pytest.raises(ValueError):select()

def trace_fixture(directory,root):
    directory.mkdir()
    def quoted(path):return '"'+''.join('\\x%02x'%v for v in str(path).encode())+'"'
    caller=quoted(root/'native-caller');app=quoted(root/'ken-rs')
    files={
        100:f'execve({caller}, [], 0x0) = 0\nclone3({{flags=CLONE_VM|CLONE_THREAD}}, 88) = 101\nclone3({{flags=CLONE_VM|CLONE_VFORK}}, 88) = 102\n',
        101:'clone(child_stack=NULL, flags=CLONE_VM|CLONE_VFORK|SIGCHLD) = 103\n',
        102:f'execve({app}, [], 0x0) = 0\nclone3({{flags=CLONE_VM|CLONE_THREAD}}, 88) = 104\n',
        103:f'execve({app}, [], 0x0) = 0\n',104:'+++ exited with 0 +++\n',
    }
    for pid,body in files.items():(directory/f'trace.{pid}').write_text(body)
    return files

def test_public_process_audit_allows_only_caller_owned_cli_processes_and_threads(tmp_path):
    from tools.rust_migration.public_search_capture import process_errors
    traces=tmp_path/'traces';root=tmp_path/'sandbox';trace_fixture(traces,root)
    assert not process_errors(traces,root,applications=2)
    with(traces/'trace.104').open('a')as stream:stream.write('connect(7, {sa_family=AF_INET}, 16) = -1 ECONNREFUSED\n')
    assert process_errors(traces,root,applications=2)

def test_cli_cannot_spawn_even_another_declared_cli_with_the_same_total_exec_count(tmp_path):
    from tools.rust_migration.public_search_capture import process_errors
    traces=tmp_path/'traces';root=tmp_path/'sandbox';files=trace_fixture(traces,root)
    (traces/'trace.101').write_text('+++ exited with 0 +++\n')
    (traces/'trace.102').write_text(files[102]+'clone(child_stack=NULL, flags=CLONE_VM|CLONE_VFORK|SIGCHLD) = 103\n')
    assert process_errors(traces,root,applications=2)

def test_missing_process_ancestry_or_a_foreign_executable_cannot_be_resealed_as_native(tmp_path):
    from tools.rust_migration.public_search_capture import process_errors
    traces=tmp_path/'traces';root=tmp_path/'sandbox';files=trace_fixture(traces,root)
    (traces/'trace.100').write_text(files[100].replace('clone3({flags=CLONE_VM|CLONE_THREAD}, 88) = 101\n',''))
    assert process_errors(traces,root,applications=2)
    (traces/'trace.100').write_text(files[100]);(traces/'trace.103').write_text('execve("\\x2f\\x62\\x69\\x6e\\x2f\\x73\\x68", [], 0x0) = 0\n')
    assert process_errors(traces,root,applications=2)

def test_public_resource_plan_contains_only_registered_native_inputs_and_no_answers():
    from tools.rust_migration.public_search_resources import plan
    value=plan(ROOT,os.environ)
    assert set(value)=={'format','files','environment','translation'}
    assert value['format']=='ken-public-search-inputs/1'
    assert value['files']['inputs/onnx/libonnxruntime.so.1.25.1']['artifact']==dict(bytes=22769624,sha256='c450a686085f441803ef914fc7e68bd417452e34ba5573344dc3dd40c0c71896')
    assert value['files']['dense-blas/libscipy_openblas64_-32a4b2a6.so']['artifact']==dict(bytes=25409073,sha256='05c9f9eb89ee68a4b9d673184fa91c99587e736392c0c2d49180a8aa5303d080')
    assert set(value['environment'])=={'KEN_POTION_SOURCE','KEN_CONTEXT_SNAPSHOT','KEN_ETTIN_SOURCE','KEN_TRANSLATION_SOURCE','KEN_GRAMMAR_MANIFEST','KEN_ORT_LIBRARY','KEN_CT2_PREPARATION','KEN_PUBLIC_RANKS'}
    assert all(Path(v['source']).is_absolute()and set(v)=={'source','artifact'}for v in value['files'].values())

def test_crossed_model_revision_is_rejected_before_any_public_resource_staging(tmp_path):
    from tools.rust_migration.public_search_resources import plan
    environment=dict(os.environ,KEN_POTION_SOURCE=str(tmp_path/'wrong-revision'))
    with pytest.raises(ValueError):plan(ROOT,environment)

def test_resource_staging_rejects_changed_source_before_writing_any_files(tmp_path):
    from tools.rust_migration.public_search_resources import stage
    from tools.rust_migration.native_json import identity
    source=tmp_path/'source';source.write_bytes(b'original')
    value=dict(files={'inputs/source':dict(source=str(source),artifact=identity(source))},environment={'KEN_CT2_PREPARATION':'inputs/runtime.json'},translation={})
    source.write_bytes(b'changed');root=tmp_path/'stage'
    with pytest.raises(ValueError):stage(value,root)
    assert not root.exists()

def test_public_execution_receipt_rejects_unexpected_evidence_and_resealed_wrong_inputs(tmp_path):
    from tools.rust_migration.public_search_capture import evidence_errors
    root=tmp_path/'sandbox';evidence=tmp_path/'evidence';evidence.mkdir()
    for pid in (102,103):
        app=evidence/f'app-{pid}';app.mkdir()
        (app/'invocation.json').write_text(json.dumps(dict(pid=pid,program=str(root/'ken-rs'),args=['mcp'],cwd=str(root/'work'/'project'))))
        for name in ('stdin','stdout','stderr'):(app/name).write_bytes(b'')
        (app/'exit').write_text('0')
        (evidence/f'loader.{pid}').write_text('calling init: /lib/libc.so.6\n')
    assert not evidence_errors(evidence,root,{102,103})
    (evidence/'loader.102').write_text('calling init: /lib/libpython3.12.so\n')
    assert evidence_errors(evidence,root,{102,103})
    (evidence/'loader.102').write_text('calling init: /lib/libc.so.6\n')
    app=evidence/'app-102';value=json.loads((app/'invocation.json').read_text());value['program']='/bin/sh';(app/'invocation.json').write_text(json.dumps(value))
    assert evidence_errors(evidence,root,{102,103})

def test_public_input_contract_cannot_add_answers_or_cross_registered_runtime_bytes():
    from tools.rust_migration.public_search_resources import plan,input_errors
    from tools.rust_migration.native_json import load
    value=plan(ROOT,os.environ);grammar=Path(os.environ['KEN_GRAMMAR_MANIFEST'])
    registration=load(Path(os.environ['KEN_CT2_PREPARATION']))['registration']
    assert not input_errors(value,ROOT,grammar,registration)
    for mutate in (
        lambda v:v['files'].update({'inputs/answers.json':dict(source='/answers',artifact=dict(bytes=2,sha256='0'*64))}),
        lambda v:v['files']['inputs/onnx/libonnxruntime.so.1.25.1']['artifact'].update(sha256='0'*64),
        lambda v:v['environment'].update(KEN_POTION_SOURCE='inputs/wrong'),
    ):
        changed=copy.deepcopy(value);mutate(changed)
        assert input_errors(changed,ROOT,grammar,registration)
