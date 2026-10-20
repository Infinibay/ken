"""Repeat every canonical judge profile without changing case/device ordering."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--platform',choices=['macos','linux'],required=True)
args=parser.parse_args()
root=args.root
area=root/'.ken/rust-migration/m2-optional'; pre=area/'preflight'
if args.platform=='linux':
    receipt=pre/'st-original-linux-repeat-check.json'
    while not receipt.exists():
        time.sleep(3)
    assert json.loads(receipt.read_text())['passed']
    reference=root/'.ken/rust-migration/m2-context/reference-t4'
    tool=pre/'transformer_capture_judge.py'
    modes=[('torch','cpu','oracle-linux-locked')]
else:
    reference=root/'.ken/rust-migration/m0-m1/reference'
    tool=root/'tools/rust_migration/transformer_capture_judge.py'
    modes=[('torch','cpu','oracle-macos-locked'),('torch','mps','oracle-macos-locked'),('mlx','mlx','oracle-mlx-macos-locked')]
first=pre/'judge-original-full-v2'
out=pre/'judge-original-full-v2-repeat'
assert not out.exists(), 'Do not overwrite a repeat capture'
out.mkdir()
env=os.environ.copy()
env.update(PYTHONPATH=str(reference/'src'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
snapshot=area/'sources/Qwen--Qwen3-Reranker-0.6B/e61197ed45024b0ed8a2d74b80b4d909f1255473'
rows=[]
for backend,device,oracle in modes:
    for dtype in ('float32','float16','bfloat16'):
        name=f'{backend}-{device}-{dtype}.json'
        command=[str(area/oracle/'bin/python'),str(tool),'--reference',str(reference),'--snapshot',str(snapshot),'--backend',backend,'--device',device,'--dtype',dtype,'--out',str(out/name)]
        with (pre/f'judge-v2-repeat-{backend}-{device}-{dtype}.log').open('wb') as log:
            result=subprocess.run(command,env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
        assert result.returncode==0, (name,result.returncode)
        a=json.loads((first/name).read_text()); b=json.loads((out/name).read_text())
        ca,cb=a['capture'],b['capture']
        assert a['platform']==b['platform']==args.platform
        for key in ('settings','model_registration','original_source_sha256','dimension','loaded_before_cases','initial_empty_call_loaded','initial_empty_error','requests','feeds','package_versions','fixed_before_native','model_inference_accepted'):
            assert ca[key]==cb[key], (name,key)
        for x,y in zip(ca['results'],cb['results'],strict=True):
            assert {k:v for k,v in x.items() if k!='elapsed_s'}=={k:v for k,v in y.items() if k!='elapsed_s'}, (name,x['id'])
        rows.append({'profile':name,'cases':len(cb['results']),'feeds':len(cb['feeds']),'byte_identical':True})
        print(json.dumps(rows[-1]),flush=True)
receipt={'passed':True,'profiles':rows,'cases':sum(r['cases'] for r in rows),'model_inference_accepted':False}
(pre/f'judge-v2-original-repeat-check-{args.platform}.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'passed':True,'profiles':len(rows),'cases':receipt['cases']}),flush=True)
