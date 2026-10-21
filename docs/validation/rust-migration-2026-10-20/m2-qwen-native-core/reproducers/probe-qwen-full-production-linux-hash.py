"""Full original Qwen feeds through the production lazy ABI, macOS only."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,signal
import numpy as np
assert np.__version__=='2.4.4'
project=Path('/app');root=project/'.ken/rust-migration/m2-optional/source-torch-core-t3-hash-linux';sys.path.insert(0,str(root))
from tools.rust_migration.transformer_reference import freeze_profile_budget,validate_original
area=project/'.ken/rust-migration/m2-optional';pre=area/'preflight'
module=area/'tensor-target-linux/release/libken_torch_backend.so'
probe=project/'.ken/rust-migration/m2-fastembed/target-final-ci/release/examples/transformer_probe'
core=area/'libtorch-linux-2.9.0';core_manifest=json.loads((pre/'libtorch-linux-preparation.json').read_text())
model=next(row for row in json.loads((root/'crates/ken-models/resources/transformer-catalog.json').read_text())['models'] if row['name']=='Qwen/Qwen3-Embedding-0.6B')
source=area/'sources/Qwen--Qwen3-Embedding-0.6B'/model['assets']['revision']
def artifact(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
runtime={'format':'ken-native-transformer/1','backend':'torch','runtimes':[{'os':'linux','arch':'aarch64','core_version':'2.9.0','module':artifact(module),'libraries':{'lib/'+r['name']:{'bytes':r['bytes'],'sha256':r['sha256']} for r in core_manifest['libraries']}}]}
tracked=[root/'Cargo.toml',root/'Cargo.lock',root/'crates/ken-models/Cargo.toml',root/'crates/ken-models/resources/transformer-catalog.json']
for folder in ('native/ken-torch-backend','crates/ken-native-model-api','crates/ken-models/src'):
 tracked += [p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.rs','.toml','.lock','.cpp')]
tracked += [root/'crates/ken-models/examples/transformer_probe.rs']
before={str(p.relative_to(root)):artifact(p) for p in tracked}

def run_native(args,*,cwd,env,stdout,stderr,timeout):
 start=time.monotonic()
 with subprocess.Popen(args,cwd=cwd,env=env,stdout=stdout,stderr=stderr,start_new_session=True) as process:
  try:
   remaining=timeout-(time.monotonic()-start)
   if remaining<=0:raise subprocess.TimeoutExpired(args,timeout)
   code=process.wait(timeout=remaining)
  except BaseException:
   try:os.killpg(process.pid,signal.SIGKILL)
   except ProcessLookupError:pass
   process.wait();raise
 return subprocess.CompletedProcess(args,code)

out=pre/'qwen-full-production-abi-linux-v3-hash';assert not out.exists();out.mkdir()
profiles=[]
source_map_sha256=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
begin={'source_files':before,'source_map_sha256':source_map_sha256,'native_module':runtime['runtimes'][0]['module'],'host_binary':artifact(probe),'execution_audit_syscalls':['execve','execveat'],'seccomp_filter':True}
(out/'BEGIN.json').write_text(json.dumps(begin,indent=2)+'\n')
with tempfile.TemporaryDirectory(prefix='ken-qwen-full-outside-',dir='/tmp') as temporary:
 work=Path(temporary);binary=work/'transformer_probe';shutil.copy2(probe,binary)
 dll=work/'backend.dylib';shutil.copy2(module,dll)
 private=work/'private';private.mkdir();(work/'home').mkdir();(work/'sentinel').mkdir();(work/'tmp').mkdir()
 env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None);env.pop('DYLD_LIBRARY_PATH',None);env.update(TMPDIR=str(work/'tmp'),PATH=str(work/'sentinel'),HOME=str(work/'home'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',LD_DEBUG='libs')
 for path in sorted((pre/'st-original-full').glob('qwen-*.json')):
  capture=json.loads(path.read_text());record={'format':'ken-transformer-original/1','platform':'linux','adapter':'sentence','capture':capture};validate_original(record)
  settings=capture['settings'];device=settings['device_request'];dtype=settings['dtype'];name=f'{device}-{dtype}'
  deadline=freeze_profile_budget(record)['execution_deadline_seconds'];cases=[];expected=[]
  for item,result in zip(capture['requests'],capture['results'],strict=True):
   assert item['id']==result['id'];vectors=np.frombuffer(bytes.fromhex(result['vectors_f32le_hex']),dtype='<f4').reshape(result['shape'])
   order=np.argsort([-len(text) for text in item['texts']]);cursor=0
   for index,feed in enumerate(capture['feeds'][result['feed_range'][0]:result['feed_range'][1]]):
    rows=feed['shape'][0];identifier=f"{item['id']}/{index}"
    cases.append({'id':identifier,'batch':feed['inputs'],'output':{'kind':'sentence'}})
    expected.append((identifier,vectors[order[cursor:cursor+rows]]));cursor+=rows
   assert cursor==len(item['texts'])
  request={'model':model,'runtime':runtime,'snapshot':str(source),'private_parent':str(private),'module':str(dll),'core_root':str(core),'device':{'kind':device},'dtype':dtype,'cases':cases}
  request_path=work/f'{name}.json';request_path.write_text(json.dumps(request))
  (out/f'{name}.inputs.json').write_bytes(request_path.read_bytes())
  start=time.monotonic()
  with (out/f'{name}.stderr').open('wb') as stderr,(out/f'{name}.json').open('wb') as stdout:
   result=run_native(['/usr/bin/strace','--seccomp-bpf','-f','-e','trace=execve,execveat','-o',str(out/f'{name}.exec.trace'),str(binary),str(request_path)],cwd=work,env=env,stdout=stdout,stderr=stderr,timeout=deadline)
  assert result.returncode==0,(name,(out/f'{name}.stderr').read_text()[-3000:])
  value=json.loads((out/f'{name}.json').read_text());trace=value['preparation']
  assert trace['device']=={'kind':device} and trace['dtype']==dtype and trace['core_version']=='2.9.0' and trace['runtime']['backend']=='torch'
  maximum=0.0;total_rows=0
  for (identifier,gold),row in zip(expected,value['rows'],strict=True):
   assert identifier==row['id'];batch=row['batch'];actual=np.asarray(batch['values'],dtype=np.float32).reshape(batch['rows'],batch['columns'])
   assert actual.shape==gold.shape and np.isfinite(actual).all();maximum=max(maximum,float(np.abs(actual-gold).max()));total_rows+=actual.shape[0]
  assert maximum<=1e-6,(name,maximum)
  libraries=(out/f'{name}.stderr').read_text();assert 'libtorch_cpu.so' in libraries and 'ken-transformer-' in libraries and 'libtorch_python' not in libraries
  trace=(out/f'{name}.exec.trace').read_text();assert trace.count('execve(')==1 and 'execveat(' not in trace
  loaded=[line.split('calling init:',1)[1].strip() for line in libraries.splitlines() if 'calling init:' in line]
  assert any('ken-transformer-' in path and path.endswith('/libtorch_cpu.so') for path in loaded)
  assert not list(private.iterdir())
  profiles.append({'device':device,'dtype':dtype,'requests':len(capture['requests']),'feeds':len(cases),'rows':total_rows,'maximum_absolute_error':maximum,'fixed_deadline_s':deadline,'elapsed_s':time.monotonic()-start,'outside_checkout':True,'actual_optional_core_loaded':True})
  assert before=={str(p.relative_to(root)):artifact(p) for p in tracked}
  assert artifact(binary)==begin['host_binary'] and artifact(dll)==begin['native_module']
  receipt={'passed':True,'profile':profiles[-1],'source_map_sha256':source_map_sha256,'source_files_unchanged':True,'host_binary':begin['host_binary'],'native_module':begin['native_module'],'execution_audit_syscalls':['execve','execveat']}
  (out/f'{name}.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
  print(json.dumps(profiles[-1]),flush=True)
assert before=={str(p.relative_to(root)):artifact(p) for p in tracked}
receipt={'passed':True,'scope':'full-Qwen3-native-core-production-ABI-linux','profiles':profiles,'native_module':runtime['runtimes'][0]['module'],'host_binary':artifact(probe),'source_files':before,'model_inference_accepted':False,'application_adapter_accepted':False}
(out/'summary.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'passed':True,'profiles':len(profiles)}),flush=True)
