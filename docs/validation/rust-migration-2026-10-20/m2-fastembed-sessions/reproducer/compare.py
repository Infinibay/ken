from pathlib import Path
import argparse,gzip,json,subprocess,time,hashlib,struct,math,os
p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--probe',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();root=a.repo.resolve();out=a.out.resolve();out.mkdir(exist_ok=False)
proof=root/'docs/validation/rust-migration-2026-10-20/m2-fastembed';catalog=json.loads((root/'crates/ken-models/resources/fastembed-catalog.json').read_text());cases=json.loads((proof/'cases.json').read_text());sources=root/'.ken/rust-migration/m2-fastembed/sources';work=root/'.ken/rust-migration/m2-fastembed/session-measurement/work'
models=['BAAI/bge-small-en-v1.5','sentence-transformers/all-MiniLM-L6-v2','sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2','Qdrant/clip-ViT-B-32-text','jinaai/jina-embeddings-v3']
def digest(path):
 with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
records=[]
for model in models:
 index=next(i for i,m in enumerate(catalog['models'])if m['name']==model);definition=catalog['models'][index];assets=definition['assets'];snapshot=sources/assets['model_id'].replace('/','--')/assets['revision']
 before={name:digest(snapshot/name)for name in assets['artifacts']}
 assert all(before[name]==record['sha256']for name,record in assets['artifacts'].items())
 request={'model':model,'cases':[{'id':c['id'],**c['input']}for c in cases if c['model']==model and c['id'].split(':')[-1]in('mixed_queries','mixed_passages')]}
 cmd=[str(a.probe.resolve()),str(root/'crates/ken-models/resources/fastembed-catalog.json'),str(sources),str(work),str(root/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json'),str(root/'.ken/rust-migration/m2/runtime-research/ort-viability/runtime/libonnxruntime.1.25.1.dylib')]
 env={**os.environ,'PATH':'/ken-native-session-no-executables'};start=time.monotonic_ns();run=subprocess.run(cmd,input=json.dumps(request),text=True,capture_output=True,env=env,cwd=work,timeout=300,check=True);elapsed=time.monotonic_ns()-start
 for name,data in [('request.json',json.dumps(request).encode()),('native.json',run.stdout.encode()),('native.stderr',run.stderr.encode())]: (out/(f'{index:02}-'+name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
 got=json.loads(run.stdout);assert got['model']==model;assert got['threads']==[0,0];assert got['optimization']=='ORT_ENABLE_ALL';assert got['preparation']['device']=='cpu';assert got['preparation']['configured_providers']==['CPUExecutionProvider'];assert got['preparation']['attempts']==[{'providers':['CPUExecutionProvider'],'error':None}]
 for platform in ['reference-macos']:
  original=json.loads(gzip.decompress((proof/platform/f'{index:02}.json.gz').read_bytes()));by_id={c['id']:c for c in original['results']}
  for case in got['results']:
   expected=by_id[case['id']];assert case['shape']==expected['shape'];assert len(case['batches'])==len(expected['batches'])
   for actual,want in zip(case['batches'],expected['batches'],strict=True):
    assert actual['output_shape']==want['outputs'][0]['shape'];assert actual['output_dtype']==want['outputs'][0]['dtype'];assert set(actual['inputs'])==set(want['inputs'])
    for name,tensor in actual['inputs'].items():assert tensor['shape']==want['inputs'][name]['shape']and tensor['values']==want['inputs'][name]['values'],(model,name)
   actual=list(struct.unpack('<'+'f'*(len(case['vectors_f32le_hex'])//8),bytes.fromhex(case['vectors_f32le_hex'])));want=list(struct.unpack('<'+'f'*(len(expected['vectors_f32le_hex'])//8),bytes.fromhex(expected['vectors_f32le_hex'])));assert len(actual)==len(want)
   assert all(math.isfinite(b)and abs(b-c)<=1e-6+1e-6*abs(c)for b,c in zip(actual,want,strict=True)),(model,platform,case['id'],max(abs(b-c)for b,c in zip(actual,want)))
 after={name:digest(snapshot/name)for name in assets['artifacts']};assert after==before;assert not list(work.iterdir())
 for name,data in [('request.json',json.dumps(request).encode()),('native.json',run.stdout.encode()),('native.stderr',run.stderr.encode())]: (out/(f'{index:02}-'+name+'.gz')).write_bytes(gzip.compress(data,mtime=0))
 records.append({'model':model,'cases':len(got['results']),'vector_rows':sum(c['shape'][0]for c in got['results']),'full_process_wall_ns':elapsed,'source_before_after':before,'native_sha256':hashlib.sha256(run.stdout.encode()).hexdigest(),'same_platform_original_exact_tokens_and_fixed_1e6_parity':True});print(model,'GREEN',flush=True)
summary={'models':records,'binary_sha256':hashlib.sha256(a.probe.read_bytes()).hexdigest(),'native_requests_contain_no_expected_outputs':True,'GPU_numerical_acceptance':False,'FastEmbed_accepted':False,'M2_accepted':False};(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
