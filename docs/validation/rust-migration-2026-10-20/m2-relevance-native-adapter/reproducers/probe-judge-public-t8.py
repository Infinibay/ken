"""Public judge comparison; frozen original scores never enter native inputs."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,signal
import numpy as np
assert np.__version__=='2.4.4'
platform='macos' if sys.platform=='darwin' else 'linux'
project=Path('/Users/andres/Projects/ken' if platform=='macos' else '/app')
area=project/'.ken/rust-migration/m2-optional';pre=area/'preflight'
root=area/('source-judge-t8-work' if platform=='macos' else 'source-judge-t8-linux')
sys.path.insert(0,str(root))
from tools.rust_migration.transformer_reference import freeze_profile_budget,validate_original
def artifact(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
manifest=json.loads((root/'SOURCE.json').read_text())
tracked=[root/r['path'] for r in manifest['files'] if r['path'].startswith(('crates/ken-models/','crates/ken-native-model-api/','native/ken-torch-backend/','native/ken-mlx-backend/')) or r['path'] in ('Cargo.toml','Cargo.lock')]
before={str(p.relative_to(root)):artifact(p) for p in tracked}
source_hash=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
probe=project/'.ken/rust-migration/m2-fastembed/target-final-ci/release/examples/relevance_probe'
captures=sorted((pre/'judge-original-full-v2').glob('*.json'))
assert len(captures)==(9 if platform=='macos' else 3)
records=[]
for path in captures:
 record=json.loads(path.read_text());validate_original(record);c=record['capture']
 assert len(c['requests'])==len(c['results'])==15
 for item,gold in zip(c['requests'],c['results'],strict=True):
  assert item['id']==gold['id']
  if gold['passed_original_call']:
   values=np.frombuffer(bytes.fromhex(gold['scores_f32le_hex']),dtype='<f4')
   assert len(values)==len(item['documents']) and np.isfinite(values).all()
  else:assert gold['exception'] in ('IndexError','ValueError')
 records.append((path,record,freeze_profile_budget(record)['execution_deadline_seconds']))
if '--preflight' in sys.argv:
 print(json.dumps({'validated_original_profiles':len(records),'cases':sum(len(r['capture']['requests']) for _,r,_ in records)}));sys.exit(0)
out=pre/f'judge-public-{platform}-t8';assert not out.exists();out.mkdir()
begin={'source_files':before,'source_map_sha256':source_hash,'host_binary':artifact(probe),'runner':artifact(Path(__file__)),'verification_snapshot':artifact(root/'SOURCE.json')}
if platform=='linux':begin.update(execution_audit_syscalls=['execve','execveat'],seccomp_filter=True)
(out/'BEGIN.json').write_text(json.dumps(begin,indent=2)+'\n')
profiles=[]
with tempfile.TemporaryDirectory(prefix='ken-judge-public-',dir='/private/tmp' if platform=='macos' else '/tmp') as temporary:
 work=Path(temporary);binary=work/'relevance_probe';shutil.copy2(probe,binary)
 for name in ('private','home','sentinel','tmp'):(work/name).mkdir()
 private=work/'private';env=os.environ.copy()
 for name in ('LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','PYTHONPATH'):env.pop(name,None)
 env.update(TMPDIR=str(work/'tmp'),PATH=str(work/'sentinel'),HOME=str(work/'home'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
 env.update({'DYLD_PRINT_LIBRARIES':'1'} if platform=='macos' else {'LD_DEBUG':'libs'})
 for path,record,deadline in records:
  capture=record['capture'];settings=capture['settings'];backend=settings['backend'];dtype=settings['dtype'];label=path.stem
  if backend=='mlx':
   assert platform=='macos';core=area/'oracle-mlx-macos-locked/lib/python3.12/site-packages/mlx'
   module=area/'mlx-target-macos-t8/release/libken_mlx_backend.dylib';version='0.32.3';device='mps'
   libraries=json.loads((pre/'mlx-primitive-native-comparison.json').read_text())['core_files']
  else:
   assert backend=='torch';core=area/f'libtorch-{platform}-2.9.0'
   module=area/('tensor-target-macos-t8/release/libken_torch_backend.dylib' if platform=='macos' else 'tensor-target-linux-t8/release/libken_torch_backend.so')
   libraries=json.loads((core/'PREPARATION.json' if platform=='macos' else pre/'libtorch-linux-preparation.json').read_text())['libraries'];version='2.9.0';device=settings['device_request']
  runtime={'format':'ken-native-transformer/1','backend':backend,'runtimes':[{'os':platform,'arch':'aarch64','core_version':version,'module':artifact(module),'libraries':{'lib/'+r['name']:{'bytes':r['bytes'],'sha256':r['sha256']} for r in libraries}}]}
  dll=work/('backend.dylib' if platform=='macos' else 'backend.so');shutil.copy2(module,dll);module_hash=artifact(module)
  model=next(m for m in json.loads((root/'crates/ken-models/resources/transformer-catalog.json').read_text())['models'] if m['name']==settings['model_id'])
  registration=capture['model_registration'];assert registration['revision']==model['assets']['revision'] and registration['model_id']==model['name']
  assert {f['path']:{'bytes':f['bytes'],'sha256':f['sha256']} for f in registration['files']}==model['assets']['artifacts']
  source=area/'sources'/model['name'].replace('/','--')/model['assets']['revision']
  cases=[{key:item[key] for key in ('id','query','documents','purpose','sequence_length')} for item in capture['requests']]
  request={'model':model,'runtime':runtime,'snapshot':str(source),'private_parent':str(private),'module':str(dll),'core_root':str(core),'device':{'kind':device},'dtype':dtype,'sequence_length':settings['sequence_length'],'batch_size':settings['batch_size'],'cases':cases}
  request_path=work/f'{label}.json';request_path.write_text(json.dumps(request));(out/f'{label}.inputs.json').write_bytes(request_path.read_bytes())
  args=[str(binary),str(request_path)]
  if platform=='linux':args=['/usr/bin/strace','--seccomp-bpf','-f','-e','trace=execve,execveat','-o',str(out/f'{label}.exec.trace'),*args]
  start=time.monotonic()
  with (out/f'{label}.stderr').open('wb') as stderr,(out/f'{label}.json').open('wb') as stdout:
   with subprocess.Popen(args,cwd=work,env=env,stdout=stdout,stderr=stderr,start_new_session=True) as process:
    try:code=process.wait(timeout=deadline)
    except BaseException:
     try:os.killpg(process.pid,signal.SIGKILL)
     except ProcessLookupError:pass
     process.wait();raise
  elapsed=time.monotonic()-start;assert code==0,(label,(out/f'{label}.stderr').read_text()[-3000:])
  value=json.loads((out/f'{label}.json').read_text());assert value['initial_preparation'] is None
  maximum=0.;scores=0;feeds=0
  for item,gold,row in zip(capture['requests'],capture['results'],value['rows'],strict=True):
   assert row['id']==gold['id']==item['id'] and row['passed_original_call']==gold['passed_original_call']
   trace=row['preparation'];actual_device='mps' if gold['device_after']=='mlx' else gold['device_after'];actual_dtype=gold['attempts'][-1]['dtype']
   assert trace['device']=={'kind':actual_device} and trace['dtype']==actual_dtype and trace['runtime']['backend']==backend and trace['core_version']==version,(label,item['id'],trace)
   if not gold['passed_original_call']:
    assert row['exception']==gold['exception'] and row['message']==gold['message'],(label,item['id'],row);continue
   observed=capture['feeds'][gold['feed_range'][0]:gold['feed_range'][1]]
   expected_feeds=[f['inputs'] if backend=='torch' else {'input_ids':f['input_ids'],'attention_mask':[[1]*n+[0]*(len(f['input_ids'][0])-n) for n in f['real_lengths']]} for f in observed]
   assert row['feeds']==expected_feeds and all(row['projection_ids']==f['projection_ids'] for f in observed),(label,item['id'],'feeds/projection')
   assert row['query_ids']==item['query_ids'] and row['remaining']==item['remaining'],(label,item['id'],'query/budget')
   expected=np.frombuffer(bytes.fromhex(gold['scores_f32le_hex']),dtype='<f4');actual=np.asarray(row['scores'],dtype=np.float32)
   assert actual.shape==expected.shape and np.isfinite(actual).all();maximum=max(maximum,float(np.abs(actual-expected).max()));scores+=len(actual);feeds+=len(expected_feeds)
  assert maximum<=1e-5 and elapsed<=deadline,(label,maximum,elapsed,deadline)
  loader=(out/f'{label}.stderr').read_text();library='libmlx.dylib' if backend=='mlx' else ('libtorch_cpu.dylib' if platform=='macos' else 'libtorch_cpu.so')
  assert 'libtorch_python' not in loader and 'libpython' not in loader and any('ken-transformer-' in line and library in line for line in loader.splitlines())
  if platform=='linux':
   execution=(out/f'{label}.exec.trace').read_text();assert execution.count('execve(')==1 and 'execveat(' not in execution
  assert not list(private.iterdir()) and before=={str(p.relative_to(root)):artifact(p) for p in tracked}
  assert artifact(binary)==begin['host_binary'] and artifact(dll)==module_hash and artifact(module)==module_hash
  profile={'model':model['name'],'backend':backend,'device':device,'dtype':dtype,'requests':len(cases),'feeds':feeds,'scores':scores,'maximum_absolute_error':maximum,'fixed_deadline_s':deadline,'elapsed_s':elapsed,'outside_checkout':True,'actual_optional_core_loaded':True}
  profiles.append(profile);receipt={'passed':True,'profile':profile,'source_map_sha256':source_hash,'source_files_unchanged':True,'host_binary':begin['host_binary'],'native_module':module_hash}
  if platform=='linux':receipt['execution_audit_syscalls']=['execve','execveat']
  (out/f'{label}.receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(profile),flush=True)
summary={'passed':True,'scope':'public-RelevanceJudge-adapter','profiles':profiles,'source_files':before,'host_binary':begin['host_binary'],'application_adapter_accepted':True,'M2_accepted':False}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'passed':True,'profiles':len(profiles)}),flush=True)
