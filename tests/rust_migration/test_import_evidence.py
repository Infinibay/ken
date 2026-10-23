"""Actual native process evidence and strict input-only protocol boundaries."""
from copy import deepcopy
import json,os,shutil,subprocess
from pathlib import Path
import pytest
from tools.rust_migration.import_validate import import_cases,run_import_capture
from tools.rust_migration.import_evidence import verify_import_capture
from tools.rust_migration.native_json import NativeJsonCapture
REPO=Path(__file__).resolve().parents[2]

@pytest.fixture(scope='module')
def capture(tmp_path_factory):
    out=tmp_path_factory.mktemp('import-evidence')/'capture';cases=import_cases(REPO)
    run_import_capture(REPO,Path(os.environ['KEN_IMPORT_PROBE']),cases,out)
    return out,cases

def test_actual_both_mode_capture_and_native_audit(capture):
    out,cases=capture;assert verify_import_capture(out,cases)==[]

@pytest.mark.parametrize('mutation',['stdout','request','resource','source','binary','exit','loader','cwd','summary'])
def test_resealed_native_execution_cannot_hide_changed_proof(capture,tmp_path,mutation):
    original,cases=capture;out=tmp_path/'capture';shutil.copytree(original,out)
    if mutation=='loader':(out/'stderr.log').write_text('libpython.so')
    else:
        file={'stdout':'stdout.json','request':'inputs.json','resource':'BUILD.json','source':'BUILD.json','binary':'BUILD.json'}.get(mutation,'execution.json')
        path=out/file;value=json.loads(path.read_bytes())
        if mutation=='stdout':value['cases'].pop()
        elif mutation=='request':value['cases'][0]['expected']={}
        elif mutation=='resource':value['resources'][0]['sha256']='0'*64
        elif mutation=='source':value['sources']['Cargo.lock']['sha256']='0'*64
        elif mutation=='binary':value['native_sha256']='0'*64
        elif mutation=='exit':value['exit']=1
        elif mutation=='cwd':value['cwd']=str(REPO)
        else:value['passed']=True
        path.write_text(json.dumps(value))
    assert verify_import_capture(out,cases)

@pytest.mark.parametrize('mutation',['top','case','import','source','hex','unicode_hex','duplicate','relative_root','kind'])
def test_native_protocol_rejects_untrusted_shape_and_encoding(mutation):
    row=dict(id='case',files=['main.ts'],imports=[dict(module='value',source_path='main.ts',language='typescript')],source=dict(kind='inputs',configs=None))
    request=dict(cases=[row])
    if mutation=='top':request['expected']={}
    elif mutation=='case':row['expected']={}
    elif mutation=='import':row['imports'][0]['expected']={}
    elif mutation=='source':row['source']['expected']={}
    elif mutation in ('hex','unicode_hex'):row['source']['configs']={'tsconfig.json':'0g'if mutation=='hex'else'\u00e9'}
    elif mutation=='duplicate':request['cases'].append(deepcopy(row))
    elif mutation=='relative_root':row['source']=dict(kind='project',root='relative')
    else:row['source']['kind']='other'
    result=subprocess.run([os.environ['KEN_IMPORT_PROBE']],input=json.dumps(request).encode(),capture_output=True,timeout=10)
    assert result.returncode!=0 and result.stdout==b''

def test_capture_rejects_interpreter_script_before_launch(tmp_path):
    script=tmp_path/'probe';script.write_text('#!/usr/bin/python3\nprint(1)\n');script.chmod(0o755)
    with pytest.raises(ValueError,match='native executable'):
        with NativeJsonCapture(script,tmp_path/'capture',repo=REPO,prefix='ken-import-process-'):pass
