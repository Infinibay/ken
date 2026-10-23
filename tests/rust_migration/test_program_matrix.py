"""Resealed compact proofs must still retain original/native semantic evidence."""
import json,shutil,tarfile
from pathlib import Path
import pytest
from tools.rust_migration.program_evidence import aggregate_program_matrix
from tools.rust_migration.native_json import identity
REPO=Path(__file__).resolve().parents[2]
PROOF=REPO/'docs/validation/rust-migration-2026-10-23/m3-program'
def seal(folder):
 rows=[dict(path=p.name,**identity(p))for p in sorted(folder.iterdir())if p.is_file()and p.name!='FILES.json']
 (folder/'FILES.json').write_text(json.dumps(dict(files=rows)))
def replay(proof,tmp_path,current=False):
 source=tmp_path/'source';source.mkdir()
 with tarfile.open(proof/'sources.tar.gz')as archive:archive.extractall(source,filter='data')
 return aggregate_program_matrix(proof,REPO,snapshot=source,current=current)
def test_actual_matrix_accepts_only_common_program_model(tmp_path):
 result=replay(PROOF,tmp_path,current=True);assert result['passed'],result
 assert result['M3d_accepted']and not result['M3_accepted']and not result['migration_complete']
@pytest.mark.parametrize('mutation',['platform','source','request','stdout','original','gate'])
def test_resealed_compressed_proof_rejects_lost_or_changed_evidence(tmp_path,mutation):
 out=tmp_path/'proof';shutil.copytree(PROOF,out);index=json.loads((out/'INDEX.json').read_bytes())
 if mutation=='platform':index['platforms'].pop('linux')
 elif mutation=='source':index['sources']['Cargo.lock']['sha256']='0'*64
 else:
  raw=tmp_path/'raw';raw.mkdir()
  with tarfile.open(out/'linux-capture.tar.gz')as archive:archive.extractall(raw,filter='data')
  if mutation=='gate':(raw/'gates/rust-tests.log').write_text('test result: ok. 7 passed; 0 failed; 0 ignored;\n')
  elif mutation=='original':
   p=raw/'original/original-observations.json';value=json.loads(p.read_bytes());value['programs'].pop();p.write_text(json.dumps(value))
  else:
   file='inputs.json'if mutation=='request'else'stdout.json';p=raw/'native'/file;value=json.loads(p.read_bytes())
   if mutation=='request':value['cases'][0]['expected']={}
   else:value['cases'].pop()
   p.write_text(json.dumps(value));receipt=raw/'native/execution.json';execution=json.loads(receipt.read_bytes());execution['request_sha256'if mutation=='request'else'stdout_sha256']=identity(p)['sha256'];receipt.write_text(json.dumps(execution))
  with tarfile.open(out/'linux-capture.tar.gz','w:gz')as archive:
   for p in raw.iterdir():archive.add(p,arcname=p.name)
 (out/'INDEX.json').write_text(json.dumps(index));seal(out)
 assert not replay(out,tmp_path)['passed']
