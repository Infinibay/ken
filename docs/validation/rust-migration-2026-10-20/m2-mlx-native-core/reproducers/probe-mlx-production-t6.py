"""Actual native MLX C ABI against all original encoder/judge feeds."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile,time,signal
import numpy as np
project=Path('/Users/andres/Projects/ken');area=project/'.ken/rust-migration/m2-optional';pre=area/'preflight';root=area/'source-mlx-t6-work'
sys.path.insert(0,str(root))
from tools.rust_migration.transformer_reference import freeze_profile_budget,validate_original
assert np.__version__=='2.4.4'
module=area/'mlx-target-macos-t6/release/libken_mlx_backend.dylib';probe=project/'.ken/rust-migration/m2-fastembed/target-final-ci/release/examples/transformer_probe'
core=area/'oracle-mlx-macos-locked/lib/python3.12/site-packages/mlx'
reference_core=json.loads((pre/'mlx-primitive-native-comparison.json').read_text());assert reference_core['passed']
def artifact(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
 return {'bytes':path.stat().st_size,'sha256':h.hexdigest()}
libraries={}
for row in reference_core['core_files']:
 value={'bytes':row['bytes'],'sha256':row['sha256']};assert artifact(core/'lib'/row['name'])==value;libraries['lib/'+row['name']]=value
runtime={'format':'ken-native-transformer/1','backend':'mlx','runtimes':[{'os':'macos','arch':'aarch64','core_version':'0.32.3','module':artifact(module),'libraries':libraries}]}
tracked=[root/p for p in ('Cargo.toml','Cargo.lock','crates/ken-models/Cargo.toml','crates/ken-models/resources/transformer-catalog.json','crates/ken-models/examples/transformer_probe.rs','crates/ken-native-model-api/Cargo.toml')]
for folder in ('native/ken-mlx-backend','crates/ken-native-model-api/src','crates/ken-models/src'):
 tracked += [p for p in (root/folder).rglob('*') if p.is_file() and not p.is_relative_to(root/'native/ken-mlx-backend/tests')]
before={str(p.relative_to(root)):artifact(p) for p in tracked};out=pre/'mlx-production-t6-v2';assert not out.exists();out.mkdir()
source_hash=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest();begin={'source_files':before,'source_map_sha256':source_hash,'native_module':artifact(module),'host_binary':artifact(probe),'runner':artifact(Path(__file__))}
(out/'BEGIN.json').write_text(json.dumps(begin,indent=2)+'\n');profiles=[]
with tempfile.TemporaryDirectory(prefix='ken-mlx-core-outside-',dir='/private/tmp') as temporary:
 work=Path(temporary);binary=work/'transformer_probe';shutil.copy2(probe,binary);dll=work/'backend.dylib';shutil.copy2(module,dll)
 for name in ('private','home','tmp','sentinel'):(work/name).mkdir()
 private=work/'private';env=os.environ.copy()
 for name in ('DYLD_LIBRARY_PATH','LD_LIBRARY_PATH','PYTHONPATH'):env.pop(name,None)
 env.update(PATH=str(work/'sentinel'),HOME=str(work/'home'),TMPDIR=str(work/'tmp'),DYLD_PRINT_LIBRARIES='1',HF_HUB_OFFLINE='1')
 for adapter,folder,pattern in [('encoder','mlx-original-full','*.json'),('judge','judge-original-full-v2','mlx-mlx-*.json')]:
  paths=sorted((pre/folder).glob(pattern));assert len(paths)==3
  for path in paths:
   capture=json.loads(path.read_text());capture=capture['capture'] if adapter=='judge' else capture
   record={'format':'ken-transformer-original/1','platform':'macos','adapter':'mlx' if adapter=='encoder' else 'judge','capture':capture};validate_original(record)
   settings=capture['settings'];model=next(m for m in json.loads((root/'crates/ken-models/resources/transformer-catalog.json').read_text())['models'] if m['name']==settings['model_id'])
   source=area/'sources'/model['name'].replace('/','--')/model['assets']['revision'];name=adapter+'-'+settings['dtype'];expected=[];cases=[]
   for item,result in zip(capture['requests'],capture['results'],strict=True):
    assert item['id']==result['id']
    if not result['passed_original_call']:assert adapter=='judge';continue
    gold=np.frombuffer(bytes.fromhex(result['vectors_f32le_hex'] if adapter=='encoder' else result['scores_f32le_hex']),dtype='<f4')
    if adapter=='encoder':gold=gold.reshape(result['shape'])
    cursor=0
    for index,feed in enumerate(capture['feeds'][result['feed_range'][0]:result['feed_range'][1]]):
     rows=len(feed['input_ids']);length=len(feed['input_ids'][0]);mask=[[1]*n+[0]*(length-n) for n in feed['real_lengths']]
     output={'kind':'mlx_last'} if adapter=='encoder' else {'kind':'yes_minus_no','true_id':feed['projection_ids'][0],'false_id':feed['projection_ids'][1]}
     identifier=f"{item['id']}/{index}";cases.append({'id':identifier,'batch':{'input_ids':feed['input_ids'],'attention_mask':mask},'output':output})
     expected.append((identifier,gold[feed['original_indices']] if adapter=='encoder' else gold[cursor:cursor+rows]));cursor+=rows
    assert cursor==len(gold)
   request={'model':model,'runtime':runtime,'snapshot':str(source),'private_parent':str(private),'module':str(dll),'core_root':str(core),'device':{'kind':'mps'},'dtype':settings['dtype'],'cases':cases}
   request_path=work/f'{name}.json';request_path.write_text(json.dumps(request));(out/f'{name}.inputs.json').write_bytes(request_path.read_bytes())
   deadline=freeze_profile_budget(record)['execution_deadline_seconds'];start=time.monotonic()
   with (out/f'{name}.json').open('wb') as stdout,(out/f'{name}.stderr').open('wb') as stderr:
    with subprocess.Popen([str(binary),str(request_path)],cwd=work,env=env,stdout=stdout,stderr=stderr,start_new_session=True) as process:
     try:code=process.wait(timeout=deadline)
     except BaseException:
      try:os.killpg(process.pid,signal.SIGKILL)
      except ProcessLookupError:pass
      process.wait();raise
   elapsed=time.monotonic()-start;assert code==0,(name,(out/f'{name}.stderr').read_text()[-3500:])
   value=json.loads((out/f'{name}.json').read_text());trace=value['preparation'];assert trace['device']=={'kind':'mps'} and trace['dtype']==settings['dtype'] and trace['core_version']=='0.32.3' and trace['runtime']['backend']=='mlx'
   maximum=0.0;rows=0
   for (identifier,gold),row in zip(expected,value['rows'],strict=True):
    assert identifier==row['id'];batch=row['batch'];actual=np.asarray(batch['values'],dtype=np.float32).reshape(batch['rows'],batch['columns'])
    if adapter=='judge':actual=actual.reshape(-1)
    assert actual.shape==gold.shape and np.isfinite(actual).all();maximum=max(maximum,float(np.abs(actual-gold).max()));rows+=len(actual)
   assert maximum<=(1e-6 if adapter=='encoder' else 1e-5) and elapsed<=deadline
   loader=(out/f'{name}.stderr').read_text();assert 'libtorch' not in loader and 'libpython' not in loader
   assert any('ken-transformer-' in line and 'libmlx.dylib' in line for line in loader.splitlines())
   assert not list(private.iterdir()) and before=={str(p.relative_to(root)):artifact(p) for p in tracked}
   assert artifact(binary)==begin['host_binary'] and artifact(dll)==begin['native_module']
   profile={'adapter':adapter,'dtype':settings['dtype'],'feeds':len(cases),'rows':rows,'maximum_absolute_error':maximum,'elapsed_s':elapsed,'fixed_deadline_s':deadline,'outside_checkout':True,'actual_optional_core_loaded':True}
   profiles.append(profile);(out/f'{name}.receipt.json').write_text(json.dumps({'passed':True,'profile':profile,'source_map_sha256':source_hash,'source_files_unchanged':True,'host_binary':begin['host_binary'],'native_module':begin['native_module']},indent=2)+'\n');print(json.dumps(profile),flush=True)
(out/'summary.json').write_text(json.dumps({'passed':True,'profiles':profiles,'source_files':before,'host_binary':begin['host_binary'],'native_module':begin['native_module'],'scope':'MLX-native-core-only','application_adapter_accepted':False,'M2_accepted':False},indent=2)+'\n')
print(json.dumps({'passed':True,'profiles':len(profiles)}),flush=True)
