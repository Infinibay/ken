"""Native process receipts authenticate actual inputs, outputs and execution."""
from copy import deepcopy
import json,os,shutil,subprocess
from pathlib import Path
import pytest
from tools.rust_migration.program_validate import program_cases,run_program_capture
from tools.rust_migration.program_evidence import verify_program_capture
REPO=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def capture(tmp_path_factory):
 out=tmp_path_factory.mktemp('program-evidence')/'capture';cases=program_cases(REPO)
 run_program_capture(REPO,Path(os.environ['KEN_PROGRAM_PROBE']),cases,out);return out,cases

def test_actual_complete_native_capture_passes(capture):
 out,cases=capture;assert verify_program_capture(out,cases)==[]

@pytest.mark.parametrize('mutation',['stdout','request','source','binary','exit','loader','cwd','summary'])
def test_resealed_native_receipt_rejects_missing_or_modified_proof(capture,tmp_path,mutation):
 original,cases=capture;out=tmp_path/'capture';shutil.copytree(original,out)
 if mutation=='loader':(out/'stderr.log').write_text('libpython.so')
 else:
  file={'stdout':'stdout.json','request':'inputs.json','source':'BUILD.json','binary':'BUILD.json'}.get(mutation,'execution.json');path=out/file;value=json.loads(path.read_bytes())
  if mutation=='stdout':value['cases'].pop()
  elif mutation=='request':value['cases'][0]['expected']={}
  elif mutation=='source':value['sources']['Cargo.lock']['sha256']='0'*64
  elif mutation=='binary':value['native_sha256']='0'*64
  elif mutation=='exit':value['exit']=1
  elif mutation=='cwd':value['cwd']=str(REPO)
  else:value['passed']=True
  path.write_text(json.dumps(value))
 assert verify_program_capture(out,cases)

@pytest.mark.parametrize('mutation',['top','case','lookup','duplicate','kind'])
def test_native_protocol_rejects_untrusted_request_shape(mutation):
 row=dict(id='case',kind='normalize',ir=dict(path='a',language='python',version='1.88.0',entities={},operations=[],facts=[],capabilities=[],diagnostics=[]),lookups=[]);request=dict(cases=[row])
 if mutation=='top':request['expected']={}
 elif mutation=='case':row['expected']={}
 elif mutation=='lookup':row['lookups']=[dict(name='x',scope=0,point=0,expected={})]
 elif mutation=='duplicate':request['cases'].append(deepcopy(row))
 else:row['kind']='other'
 actual=subprocess.run([os.environ['KEN_PROGRAM_PROBE']],input=json.dumps(request).encode(),capture_output=True,timeout=10)
 assert actual.returncode!=0 and actual.stdout==b''
