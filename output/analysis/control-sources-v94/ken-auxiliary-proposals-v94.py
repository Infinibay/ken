"""ALL480 mixed auxiliary public251pools before either training-label delivery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import ken
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
from ken.bench.source_receipts import verify_frozen_source


def sha(path):
 with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


parser=argparse.ArgumentParser()
for name in('source','output'):parser.add_argument('--'+name,type=Path,required=True)
parser.add_argument('--source-registration-sha256',required=True)
args=parser.parse_args();S=args.source;O=args.output
receipt=verify_frozen_source(E)
assert receipt=='65d758ced0ece64d1f77fbac11ac5e7738dec7dfb3dbb82db6afd843b1833ad0'
worker=Path('/private/tmp/ken-auxiliary-features-worker-v94.py')
assert sha(worker)=='ee6dc5b213f6c61e54b350ab2adbab9d029133a5e8e64f400d6bc0ee2833c240'
assert sha(S/'registration.json')==args.source_registration_sha256
source=json.loads((S/'registration.json').read_text())
assert source['complete']and source['engine_receipt']=='4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d'
assert source['script_sha256']=='48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61'
assert len(source['source_repos'])==len(source['context_repos'])==len(source['views_repos'])==8
assert all(sha(path)==digest for path,digest in source['inputs'].items())
AUX=Path('/private/tmp/ken-search-auxiliary-training-20261015').resolve()
sealed=[
 ('v1','seal.json','cases.jsonl','requests.jsonl',96,
  'bd84e1af801f271f7643a39f9010e1b8d11965e3a564a66ea814aee47c3fd7c7',
  '1d9152342ef3c9a547461c07775d25fc556f1937ab7c48ae35009f2d79bdfcf1',
  '02d18ab1d6a603cc29d89ec3bc57087353f0d4139120d9a1f8e9944115970473',
  'fa2f0499bfacf6ae2fbe29dc3e809c9144c701031d4f00fc07397e61af2f97a9',
  'e2cd83b6d827b86c535600dec54d740a06e1d7ee2e11f1425daeb0ab5530e3ef'),
 ('v2','seal2.json','cases2.jsonl','requests2.jsonl',384,
  '707af911d1fab3a735f023abb23f5dc266676fb8c53fbf3abb5f8527fd5911fc',
  'b2d7949a2319c2c10bcef5177b9aac2c80baab6af4155b2b851d21a2eeaa5ac7',
  '0a7524506ac4fee58121e7fbabff5520cb421f7fc74ed844fce7bf04753644b8',
  '0fbebb36cf32fbe7477078c5af1028b6752a77e80cc7d39a64791c901ed66639',
  'bd0c98063d61b3b0a1c5bbb74a05e2dda7fcedaa20f95d58bc496dff59bb4528')]
curation={};rows=[];parts=[]
for pilot,seal_name,cases_name,requests_name,count,receipt_sha,archive_sha,seal_sha,cases_sha,requests_sha in sealed:
 receipt_path=AUX/f'receipt-auxiliary-training-{pilot}.json';archive=AUX/f'auxiliary-training-pilot-{pilot}.sealed.tar.gz'
 leaf_path=AUX/f'pilot-{pilot}'/seal_name;requests=AUX/f'pilot-{pilot}'/requests_name
 assert sha(receipt_path)==receipt_sha and sha(archive)==archive_sha and sha(leaf_path)==seal_sha
 envelope=json.loads(receipt_path.read_text());leaf=json.loads(leaf_path.read_text())
 assert envelope['seal']['sha256']==seal_sha and envelope['sealed_archive']['sha256']==archive_sha
 assert envelope['cases']['sha256']==leaf['files'][cases_name]['sha256']==cases_sha
 assert envelope['requests']['sha256']==leaf['files'][requests_name]['sha256']==requests_sha==sha(requests)
 public=list(map(json.loads,requests.read_text().splitlines()));assert len(public)==count
 rows.extend(public);parts.append({'pilot':pilot,'queries':count,'cases_path':str(AUX/f'pilot-{pilot}'/cases_name),'cases_sha256':cases_sha,'requests_path':str(requests),'requests_sha256':requests_sha})
 curation.update({str(path):sha(path)for path in(receipt_path,archive,leaf_path,requests)})
assert len(rows)==len({r['id']for r in rows})==480
assert all(set(r)=={'id','repo_id','request'}and isinstance(r['id'],str)and r['id'].strip()and isinstance(r['repo_id'],str)and r['repo_id'].strip()for r in rows)
assert all(set(r['request'])=={'query','purpose','target','limit','max_chars'}and r['request']['purpose']=='auto'and r['request']['target']=='symbol'and r['request']['limit']==10 and r['request']['max_chars']==12000 and isinstance(r['request']['query'],str)and r['request']['query'].strip()for r in rows)
assert {r['repo_id']for r in rows}==set(source['source_repos'])
assert all(sum(r['repo_id']==repo for r in rows)==60 for repo in source['source_repos'])
O.mkdir(exist_ok=False)
for name in('requests','workers','indices'):(O/name).mkdir()
protocol=E/'experiments/search-engine/cpu-auxiliary-mixed-training-v94.md'
manifest={'scope':'ALL480 independently sealed TRAINING publicrequests from2pilots, original251features before labels; source93reused with identical producer/core/encoders; no numericmodel or fit','engine_receipt':receipt,'source_engine_receipt':source['engine_receipt'],'script_sha256':sha(__file__),'worker_sha256':sha(worker),'protocol_sha256':sha(protocol),'source_registration_sha256':args.source_registration_sha256,'source_root':str(S),'inputs':{str(S/'registration.json'):args.source_registration_sha256,str(protocol):sha(protocol),**curation},'curation_bindings':curation,'pilots':parts,'source_repos':source['source_repos'],'repos':{},'source_phase_complete':True}
for repo in sorted(source['source_repos']):
 path=S/'indices'/(repo+'.db');expected=source['source_repos'][repo]['new_source_index_sha256'];assert sha(path)==expected
 shutil.copyfile(path,O/'indices'/(repo+'.db'));assert sha(O/'indices'/(repo+'.db'))==expected
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
environment=dict(os.environ,PYTHONPATH=str(E/'src'),KEN_INDEX_WORKERS='0',HF_HUB_OFFLINE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1',TOKENIZERS_PARALLELISM='false',CUDA_VISIBLE_DEVICES='')
with(O/'candidates.jsonl').open('w')as output:
 for repo in sorted(source['source_repos']):
  public=[row for row in rows if row['repo_id']==repo];request_file=O/'requests'/(repo+'.jsonl');request_file.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n'for row in public));folder=O/'workers'/repo;started=time.perf_counter()
  with(O/'workers'/(repo+'-stdout.log')).open('w')as stdout,(O/'workers'/(repo+'-stderr.log')).open('w')as stderr:
   result=subprocess.run([sys.executable,str(worker),'--source',str(S),'--repo',repo,'--source-registration-sha256',args.source_registration_sha256,'--requests',str(request_file),'--requests-sha256',sha(request_file),'--output',str(folder)],env=environment,stdout=stdout,stderr=stderr)
  if result.returncode:raise RuntimeError(f'auxiliary94 worker {repo} exited {result.returncode}; no query exclusion, partial artifacts retained')
  saved=list(map(json.loads,(folder/'candidates.jsonl').read_text().splitlines()));assert len(saved)==len({row['id']for row in saved})==60 and {row['id']for row in saved}=={row['id']for row in public}
  output.write((folder/'candidates.jsonl').read_text());output.flush();shutil.copyfile(folder/'features.npz',O/(repo+'.npz'))
  record=json.loads((folder/'registration.json').read_text());assert record['complete']and record['engine_receipt']==receipt and record['source_engine_receipt']==source['engine_receipt']
  manifest['repos'][repo]={'queries':60,'rows':sum(len(row['candidates'])for row in saved),'requests_sha256':sha(request_file),'features_sha256':sha(O/(repo+'.npz')),'worker_registration_sha256':sha(folder/'registration.json'),'exit_code':0,'ms':(time.perf_counter()-started)*1000}
  (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'prepared_repository':repo,'queries':60,'rows':manifest['repos'][repo]['rows']}),flush=True)
assert len(manifest['repos'])==8 and all(sha(path)==digest for path,digest in manifest['inputs'].items())
assert verify_frozen_source(E)==receipt and sha(worker)==manifest['worker_sha256']
manifest.update(complete=True,candidates_sha256=sha(O/'candidates.jsonl'))
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
