from pathlib import Path
import json,os,shutil,sys
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_missing_symbol_views_capture_rejects_summary(tmp_path):
    from tools.rust_migration.symbol_views_host import verify_capture
    (tmp_path/'summary.json').write_text('{"passed":true}');assert verify_capture(tmp_path,ROOT)

@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_SYMBOL_VIEWS_PACKET',ROOT/'.ken/rust-migration/symbol-views/packet'))
    out=tmp_path/'packet';shutil.copytree(source,out);return out

def test_actual_symbol_views_capture_uses_native_first_and_second_scores(packet):
    from tools.rust_migration.symbol_views_host import verify_capture
    assert not verify_capture(packet,ROOT)

@pytest.mark.parametrize('change',['input-answer','card-score','code-score','order','calls','binary','source','generated','original','parent'])
def test_resealed_symbol_views_capture_rejects(packet,change):
    from tools.rust_migration.symbol_views_host import verify_capture
    from tools.rust_migration.native_json import identity
    assert not verify_capture(packet,ROOT)
    out=packet/'symbol-views';capture=out/'native';execution=capture/'execution.json';record=json.loads(execution.read_bytes())
    if change=='input-answer':
        path=capture/'inputs.json';value=json.loads(path.read_bytes());value['expected']={};path.write_text(json.dumps(value));record['request_sha256']=identity(path)['sha256']
    elif change in('card-score','code-score','order','calls'):
        path=capture/'stdout.json';value=json.loads(path.read_bytes());row=value['results'][0]
        if change=='card-score':row['result']['original_scores'][0]+=1.
        elif change=='code-score':row['result']['code_scores'][0]+=1.
        elif change=='order':row['result']['order']=[]
        else:row['calls']=[]
        path.write_text(json.dumps(value));record['stdout_sha256']=identity(path)['sha256']
    elif change=='binary':(out/'bin/symbol_views_probe').write_bytes(b'changed')
    elif change=='source':
        name=next(n for n in record['owned_before']if n.startswith('source/'));record['owned_before'][name]['sha256']='a'*64;record['owned_after'][name]['sha256']='a'*64
    elif change=='generated':record['owned_after'].pop('prepared/model.onnx')
    elif change=='original':(out/'ORIGINAL.json.gz').write_bytes(b'changed')
    else:(packet/'SDK.json').unlink()
    execution.write_text(json.dumps(record));assert verify_capture(packet,ROOT)

def test_scoped_python_gate_binds_junit_command_and_completion(tmp_path):
    from tools.rust_migration.command_gates import python_scope_commands,python_scope_errors
    from tools.rust_migration.native_json import identity
    out=tmp_path/'symbol-views';gates=out/'gates';gates.mkdir(parents=True)
    file='tests/rust_migration/test_symbol_views_host.py'
    (out/'PYTHON-OUTPUT.json').write_text(json.dumps(dict(format='ken-native-python-scope/1',recorded_directory=str(out.resolve()))))
    (gates/'python-list.log').write_text(file+'::test_fixture\n');(gates/'python-tests.log').write_text('synthetic command consistency only\n')
    (gates/'python.xml').write_text('<testsuites><testsuite><testcase classname="tests.rust_migration.test_symbol_views_host" name="test_fixture"/></testsuite></testsuites>')
    commands=python_scope_commands(sys.executable,[file],out.resolve())
    records={name:dict(command=cmd,exit=0,log=identity(gates/(name+'.log')))for name,cmd in commands.items()}
    path=gates/'PYTHON.json';path.write_text(json.dumps(records));assert not python_scope_errors(out,[file],1)
    records['python-tests']['command'][-1]='--junitxml=/tmp/python.xml';path.write_text(json.dumps(records));assert python_scope_errors(out,[file],1)
