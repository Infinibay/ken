"""Reproduce the actual old false acceptance, then reject resealed identities."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys
from tools.rust_migration.integration_validate import aggregate_integration

repo=Path.cwd();ws=repo/'.superpowers/sdd/2026-10-21-rust-model-integration'
base=repo/'.ken/rust-migration/m2-integration/source-6eca4cb1'
source=base/'docs/validation/rust-migration-2026-10-21/m2-integration'
target=ws/'review-matrix-controls'
shutil.copytree(source,target)
baseline=aggregate_integration(target,base);assert baseline['passed'],baseline
manifest_path=target/'FILES.json';manifest_raw=manifest_path.read_bytes();results=[]
for system,phase in [('linux','offline'),('macos','public')]:
 for mutation in ['prepared','model_fingerprint','verified_artifacts_fingerprint']:
  path=f'{system}/roles/fastembed-{phase}/stdout.json';file=target/path;original=file.read_bytes()
  try:
   row=json.loads(original);observed=row['rows'][0]
   if mutation=='prepared':observed['prepared']=False
   else:observed['preparation']['trace'][mutation]='f'*64
   raw=(json.dumps(row)+'\n').encode();file.write_bytes(raw)
   manifest=json.loads(manifest_raw);entry=next(e for e in manifest['files']if e['path']==path)
   entry.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());manifest_path.write_text(json.dumps(manifest)+'\n')
   if not results:
    code='import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from tools.rust_migration.integration_validate import aggregate_integration;print(json.dumps(aggregate_integration(Path(sys.argv[2]),Path(sys.argv[1]))))'
    run=subprocess.run([sys.executable,'-I','-c',code,str(base),str(target)],capture_output=True,text=True,check=True,timeout=60)
    previous=json.loads(run.stdout);assert previous['passed']and previous['M2_accepted'],previous
    (ws/'review-original-false-acceptance.json').write_text(json.dumps(previous,indent=2)+'\n')
   result=aggregate_integration(target,base);assert not result['passed']and not result['M2_accepted'],(system,phase,mutation)
   results.append(dict(system=system,phase=phase,mutation=mutation,rejected=True,errors=result['errors']))
  finally:file.write_bytes(original);manifest_path.write_bytes(manifest_raw)
assert aggregate_integration(target,base)['passed']
(ws/'review-controls.json').write_text(json.dumps(dict(original_false_acceptance_reproduced=True,controls=results,all_rejected=True),indent=2)+'\n')
shutil.rmtree(target)
print('Original false acceptance reproduced; all6resealed whole-matrix preparation mutations rejected; restored matrix passes.')
