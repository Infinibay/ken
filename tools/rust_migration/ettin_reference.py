"""Capture pinned preparation and paired raw logits from frozen original only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from .context_reference import stderr_errors
from .reference import Reference,reference_env,verify_reference

TOLERANCES={'atol':1e-5,'rtol':1e-5}


def ettin_cases()->list[dict]:
    def case(name,query,texts,options=None):
        return {'id':name,'options':options or {},'calls':[{'op':'tokens','query':query,'texts':texts},
                                                        {'op':'score','query':query,'texts':texts}]}
    rows=[{'id':'empty-pool','options':{},'calls':[{'op':'score','query':'x','texts':[]}]},
        case('empty-query','',['x']),case('empty-document','x',['']),
        case('spanish','¿Dónde se guarda configuración?',['def save_config(path): write_json(path, config)','return a*b']),
        case('code','config.value = read_json(path)',['def load_config(path): return read_json(path)']),
        case('unicode','café',['cafe\u0301','café']),case('emoji-nul','🙂\x00',['🚀 config\x00']),
        case('repeated-documents','x',['x','y','x']),case('pool10','x',['x','y']*5),
        {'id':'empty-pool-then-score','options':{},'calls':[{'op':'score','query':'x','texts':[]},
                                                         {'op':'score','query':'x','texts':['y']}]},
        case('batch3-remainder','x',['','x','y y','x x x','z','x y','y'],{'batch_size':3})]
    for count in (1023,1024,1025):
        row=case(f'pair-boundary{count}','x',[' alpha'*(count-4)])
        row['untruncated_pair_tokens']=count;rows.append(row)
    rows += [case('long-document','x',[' alpha'*4097]),
        case('query-capacity-allowed',' alpha'*1020,['y']),
        {'id':'query-capacity-rejected','options':{},'calls':[{'op':'score','query':' alpha'*1021,'texts':['y']}]},
        case('query-char-limit-allowed','-'*65536,['y']),
        {'id':'query-char-limit-rejected','options':{},'calls':[{'op':'score','query':'-'*65537,'texts':['y']}]},
        {'id':'pool11-rejected','options':{},'calls':[{'op':'score','query':'x','texts':['y']*11}]},
        case('custom-budget512','x',[' alpha'*1000],{'max_tokens':512}),
        case('custom-budget2048','x',[' alpha'*1500],{'max_tokens':2048}),
        {'id':'pair-fits-before-and-after-truncation','options':{},'calls':[
            {'op':'pair_fits','query':'x','text':' alpha'*1020},
            {'op':'pair_fits','query':'x','text':' alpha'*1021},
            {'op':'score','query':'x','texts':[' alpha'*1021]}]}]
    return rows


def source_state(root:Path,definition:dict)->dict:
    if not root.is_dir() or root.name!=definition['revision']:raise ValueError('registered source revision required')
    state={}
    for name,expected in definition['artifacts'].items():
        path=root/name
        if not path.is_file() or path.stat().st_size!=expected['bytes']:raise ValueError(f'source artifact size: {name}')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=expected['sha256']:raise ValueError(f'source artifact hash: {name}')
        state[name]={'bytes':expected['bytes'],'sha256':digest}
    return state


_CHILD=r'''
import dataclasses,hashlib,json,platform,resource,sys,time
from pathlib import Path
from importlib.metadata import version
import ken.retrieval.neural_assets as implementation
from ken.retrieval.neural_reranker import ONNXReranker,RerankerAssets
request=json.load(sys.stdin);reference=Path(request['reference']);definition=request['definition']
if not Path(implementation.__file__).resolve().is_relative_to(reference/'src'):raise ValueError('original import escaped frozen tree')
source=Path(request['source']);destination=Path(request['destination'])
started=time.monotonic_ns()
if request.get('prepared'):
 prepared=Path(request['prepared']);pins=definition['source']['artifacts']
 assets=RerankerAssets(prepared/definition['graph']['path'],definition['graph']['sha256'],
  prepared/'tokenizer.json',pins['tokenizer.json']['sha256'],prepared/'config.json',pins['config.json']['sha256'],
  prepared/'tokenizer_config.json',pins['tokenizer_config.json']['sha256']);assets.verify()
else:assets=implementation.prepare_reranker(definition,destination,source_snapshot=source)
prepare_ns=time.monotonic_ns()-started
artifact_paths={'model.onnx':assets.graph,'tokenizer.json':assets.tokenizer,'config.json':assets.config,'tokenizer_config.json':assets.tokenizer_config}
artifacts={name:{'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for name,path in artifact_paths.items()}
def peak():
 if sys.platform.startswith('linux'):
  for line in Path('/proc/self/status').read_text().splitlines():
   if line.startswith('VmHWM:'):return int(line.split()[1])*1024
  raise ValueError('missing VmHWM')
 return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rows=[];boundaries={}
for case in request['cases']:
 started=time.monotonic_ns();encoder=ONNXReranker(lambda:assets,**case['options']);constructor_ns=time.monotonic_ns()-started
 calls=[];started=time.monotonic_ns()
 for call in case['calls']:
  try:
   if call['op']=='score':
    scores,details=encoder.score(call['query'],call['texts']);value={'scores':scores,'details':details}
   elif call['op']=='tokens':
    encoder._load();encoded=encoder._tokenizer.encode_batch([(call['query'],text) for text in call['texts']])
    value=[{'ids':e.ids,'attention_mask':e.attention_mask,'overflowing':bool(e.overflowing)} for e in encoded]
   elif call['op']=='pair_fits':value=encoder.pair_fits(call['query'],call['text'])
   else:raise KeyError('unknown original operation')
  except ValueError as error:value={'error':{'type':type(error).__name__,'message':str(error)}}
  calls.append(value)
 if 'untruncated_pair_tokens' in case:
  call=case['calls'][0];actual=len(encoder._query_tokenizer.encode(call['query'],call['texts'][0]).ids)
  if actual!=case['untruncated_pair_tokens']:raise ValueError(f'raw pair boundary mismatch: {actual}')
  boundaries[case['id']]=actual
 session=encoder._session
 options=session.get_session_options() if session is not None else None
 rows.append({'id':case['id'],'calls':calls,'constructor_ns':constructor_ns,'calls_ns':time.monotonic_ns()-started,
  'peak_bytes':peak(),'session_loaded':session is not None,'providers':session.get_providers() if session else [],
  'cpu_arena':options.enable_cpu_mem_arena if options else None,
  'intra_threads':options.intra_op_num_threads if options else None,'inter_threads':options.inter_op_num_threads if options else None})
print(json.dumps({'oracle':{'frozen_import':True,'runtime':{k:version(k) for k in ['numpy','onnxruntime','onnx','tokenizers']}},
 'platform':platform.system(),'architecture':platform.machine(),'definition':definition,'cases':request['cases'],
 'artifacts':artifacts,'prepare_ns':prepare_ns,'results':rows,'boundary_characterization':boundaries},allow_nan=False))
'''


def capture(reference:Reference,source:Path,output:Path,*,cases:list[dict]|None=None,
            definition:dict|None=None,prepared:Path|None=None)->dict:
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    if definition is None:definition=json.loads((reference.root/'src/ken/embedder/data/ettin-68m-fp32.json').read_text())
    source=source.resolve();before=source_state(source,definition['source'])
    cases=ettin_cases() if cases is None else cases
    if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('distinct nonempty histories required')
    output=output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-ettin-original-') as directory:
        root=Path(directory);request={'reference':str(reference.root),'definition':definition,'source':str(source),
            'destination':str(root/'prepared'),'prepared':str(prepared.resolve()) if prepared else None,'cases':cases}
        child=subprocess.run([str(reference.python),'-c',_CHILD],cwd=root,env=reference_env(reference,root/'environment'),
            input=json.dumps(request),text=True,capture_output=True,timeout=600)
    output.with_suffix('.stderr.log').write_text(child.stderr)
    if child.returncode:raise ValueError(f'frozen Ettin capture failed: {child.stderr}')
    result=json.loads(child.stdout)
    if stderr_errors(child.stderr,result['platform']):raise ValueError(f'unexpected original stderr: {child.stderr}')
    if source_state(source,definition['source'])!=before:raise ValueError('source artifacts changed during capture')
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    result.update(format='ken-ettin-oracle/1',source_artifacts=before,reference_fingerprint=reference.fingerprint,tolerances=TOLERANCES)
    result['oracle']['stderr']=child.stderr
    output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');return result
