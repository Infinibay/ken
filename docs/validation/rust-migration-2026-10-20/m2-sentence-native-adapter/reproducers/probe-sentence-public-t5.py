"""Compare the public text API with every frozen original ST profile."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,signal
import numpy as np
assert np.__version__=='2.4.4'
platform='macos' if sys.platform=='darwin' else 'linux'
project=Path('/Users/andres/Projects/ken' if platform=='macos' else '/app')
area=project/'.ken/rust-migration/m2-optional';pre=area/'preflight'
root=area/('source-transformer-t5-work' if platform=='macos' else 'source-transformer-t5-linux')
sys.path.insert(0,str(root))
from tools.rust_migration.transformer_reference import freeze_profile_budget,validate_original
module=area/('tensor-target-macos-t5/release/libken_torch_backend.dylib' if platform=='macos' else 'tensor-target-linux-t5/release/libken_torch_backend.so')
probe=project/'.ken/rust-migration/m2-fastembed/target-final-ci/release/examples/sentence_probe'
core=area/f'libtorch-{platform}-2.9.0'
core_record=core/'PREPARATION.json' if platform=='macos' else pre/'libtorch-linux-preparation.json'
core_manifest=json.loads(core_record.read_text())
def artifact(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
runtime={'format':'ken-native-transformer/1','backend':'torch','runtimes':[{'os':platform,'arch':'aarch64','core_version':'2.9.0','module':artifact(module),'libraries':{'lib/'+r['name']:{'bytes':r['bytes'],'sha256':r['sha256']} for r in core_manifest['libraries']}}]}
tracked=[root/p for p in ('Cargo.toml','Cargo.lock','crates/ken-models/Cargo.toml','crates/ken-models/resources/transformer-catalog.json','crates/ken-models/examples/sentence_probe.rs','native/ken-torch-backend/build.rs','native/ken-torch-backend/Cargo.toml','native/ken-torch-backend/Cargo.lock','crates/ken-native-model-api/Cargo.toml')]
for folder in ('native/ken-torch-backend/src','crates/ken-native-model-api/src','crates/ken-models/src'):
 tracked += [p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.rs','.cpp')]
before={str(p.relative_to(root)):artifact(p) for p in tracked}
out=pre/f'sentence-public-{platform}-t5-v2';assert not out.exists();out.mkdir()
source_hash=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
begin={'source_files':before,'source_map_sha256':source_hash,'native_module':artifact(module),'host_binary':artifact(probe),'runner':artifact(Path(__file__)),'verification_snapshot':artifact(root/'SOURCE.json')}
if platform=='linux':begin.update(execution_audit_syscalls=['execve','execveat'],seccomp_filter=True)
(out/'BEGIN.json').write_text(json.dumps(begin,indent=2)+'\n')
def run(args,**kwargs):
 with subprocess.Popen(args,start_new_session=True,**kwargs) as process:
  try:return process.wait(timeout=deadline)
  except BaseException:
   try:os.killpg(process.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   process.wait();raise
def public_side(side):
 assert side in ('query','passages'),side
 return 'query' if side=='query' else 'passage'
assert public_side('query')=='query' and public_side('passages')=='passage'
profiles=[]
with tempfile.TemporaryDirectory(prefix='ken-sentence-public-',dir='/private/tmp' if platform=='macos' else '/tmp') as temporary:
 work=Path(temporary);binary=work/'sentence_probe';shutil.copy2(probe,binary)
 dll=work/('backend.dylib' if platform=='macos' else 'backend.so');shutil.copy2(module,dll)
 for name in ('private','home','sentinel','tmp'):(work/name).mkdir()
 private=work/'private'
 env=os.environ.copy()
 for name in ('LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','PYTHONPATH'):env.pop(name,None)
 env.update(TMPDIR=str(work/'tmp'),PATH=str(work/'sentinel'),HOME=str(work/'home'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
 env.update({'DYLD_PRINT_LIBRARIES':'1'} if platform=='macos' else {'LD_DEBUG':'libs'})
 captures=sorted((pre/'st-original-full').glob('*.json'))
 assert len(captures)==(12 if platform=='macos' else 6)
 for path in captures:
  capture=json.loads(path.read_text());record={'format':'ken-transformer-original/1','platform':platform,'adapter':'sentence','capture':capture};validate_original(record)
  settings=capture['settings'];device=settings['device_request'];dtype=settings['dtype'];label=path.stem
  model=next(m for m in json.loads((root/'crates/ken-models/resources/transformer-catalog.json').read_text())['models'] if m['name']==settings['model_id'])
  registration=capture['model_registration']
  assert registration['model_id']==model['name'] and registration['revision']==model['assets']['revision']
  assert {f['path']:{'bytes':f['bytes'],'sha256':f['sha256']} for f in registration['files']}==model['assets']['artifacts']
  source=area/'sources'/model['name'].replace('/','--')/model['assets']['revision']
  cases=[{'id':item['id'],'side':public_side(item['side']),'texts':item['texts']} for item in capture['requests']]
  request={'model':model,'runtime':runtime,'snapshot':str(source),'private_parent':str(private),'module':str(dll),'core_root':str(core),'device':{'kind':device},'dtype':dtype,'sequence_length':settings['sequence_length'],'batch_size':settings['batch_size'],'cases':cases}
  request_path=work/f'{label}.json';request_path.write_text(json.dumps(request));(out/f'{label}.inputs.json').write_bytes(request_path.read_bytes())
  deadline=freeze_profile_budget(record)['execution_deadline_seconds'];args=[str(binary),str(request_path)]
  if platform=='linux':args=['/usr/bin/strace','--seccomp-bpf','-f','-e','trace=execve,execveat','-o',str(out/f'{label}.exec.trace'),*args]
  start=time.monotonic()
  with (out/f'{label}.stderr').open('wb') as stderr,(out/f'{label}.json').open('wb') as stdout:code=run(args,cwd=work,env=env,stdout=stdout,stderr=stderr)
  elapsed=time.monotonic()-start
  assert code==0,(label,(out/f'{label}.stderr').read_text()[-3000:])
  value=json.loads((out/f'{label}.json').read_text());trace=value['preparation']
  assert value['initial_preparation'] is None and value['after_empty_preparation'] is None and value['empty_vectors']==[]
  assert value['dimension']==capture['dimension'] and trace['device']=={'kind':device} and trace['dtype']==dtype and trace['core_version']=='2.9.0' and trace['runtime']['backend']=='torch'
  maximum=0.0;total_rows=0;feeds=0
  for item,gold,row in zip(capture['requests'],capture['results'],value['rows'],strict=True):
   assert row['id']==gold['id']==item['id'] and row['counts']==capture['counts'][item['id']]
   expected_feeds=[feed['inputs'] for feed in capture['feeds'][gold['feed_range'][0]:gold['feed_range'][1]]]
   assert row['feeds']==expected_feeds,(label,item['id'],'token feeds differ')
   # Both registered models have no default ST prompt. Ken prefixes are
   # constant across a request, so this independently checks exact tie order.
   assert row['order']==np.argsort([-len(text) for text in item['texts']]).tolist()
   assert row['preparation']['device']=={'kind':device} and row['preparation']['dtype']==dtype
   expected=np.frombuffer(bytes.fromhex(gold['vectors_f32le_hex']),dtype='<f4').reshape(gold['shape']);actual=np.asarray(row['vectors'],dtype=np.float32)
   assert actual.shape==expected.shape and np.isfinite(actual).all();maximum=max(maximum,float(np.abs(actual-expected).max()));total_rows+=len(actual);feeds+=len(expected_feeds)
  assert maximum<=1e-6 and elapsed<=deadline,(label,maximum,elapsed,deadline)
  loader=(out/f'{label}.stderr').read_text();library='libtorch_cpu.dylib' if platform=='macos' else 'libtorch_cpu.so'
  assert 'libtorch_python' not in loader and any('ken-transformer-' in line and library in line for line in loader.splitlines())
  if platform=='linux':
   execution=(out/f'{label}.exec.trace').read_text();assert execution.count('execve(')==1 and 'execveat(' not in execution
  assert not list(private.iterdir()) and before=={str(p.relative_to(root)):artifact(p) for p in tracked}
  assert artifact(binary)==begin['host_binary'] and artifact(dll)==begin['native_module']
  profile={'model':model['name'],'device':device,'dtype':dtype,'requests':len(cases),'feeds':feeds,'rows':total_rows,'maximum_absolute_error':maximum,'fixed_deadline_s':deadline,'elapsed_s':elapsed,'outside_checkout':True,'actual_optional_core_loaded':True}
  profiles.append(profile)
  receipt={'passed':True,'profile':profile,'source_map_sha256':source_hash,'source_files_unchanged':True,'host_binary':begin['host_binary'],'native_module':begin['native_module']}
  if platform=='linux':receipt['execution_audit_syscalls']=['execve','execveat']
  (out/f'{label}.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(profile),flush=True)
summary={'passed':True,'scope':'public-SentenceEncoder-adapter','profiles':profiles,'source_files':before,'host_binary':begin['host_binary'],'native_module':begin['native_module'],'application_adapter_accepted':True,'M2_accepted':False}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'passed':True,'profiles':len(profiles)}),flush=True)
