"""Capture model-name/prompt decisions through the frozen original owners."""
from __future__ import annotations

from copy import deepcopy
import itertools
import json
from pathlib import Path
import subprocess
import tempfile

from .reference import Reference, reference_env, verify_reference

LEGACY='sentence-transformers/all-MiniLM-L6-v2'
FORCED=[None,'','forced/model',' ','\x1c','\0']


def _case(name,config,environment,recorded,embedding,slot,visible=True,*,null_marker=False,doc_space='1'):
    return {'id':name,'input':{'user_config':deepcopy(config),'environment':environment,
        'project_visible':visible,'facts':{'recorded_model':recorded,
        'file_vectors_present':embedding is not None or slot is not None},
        'forced_variants':list(FORCED)},'source_setup':{'embedding_hex':embedding,
        'vec_slot':slot,'null_recorded_marker':null_marker,'document_space':doc_space}}


def policy_cases()->list[dict]:
    configs=[None,{}, {'default_model':''},{'default_model':'\x1c\xa0'},
        {'default_model':' user/default '},{'default_model':'\u200b'},
        {'default_model':LEGACY},{'default_model':17}]
    environments=[None,'','env/model',' '];recorded=[None,'','stored/model',LEGACY,' ']
    vectors=[(None,None),('00',None),(None,7),('00',7)]
    rows=[]
    for d,e,m,v,p in itertools.product(range(8),range(4),range(5),range(4),range(2)):
        embedding,slot=vectors[v]
        rows.append(_case(f'cartesian-{d}-{e}-{m}-{v}-{p}',configs[d],environments[e],
            recorded[m],embedding,slot,bool(p)))
    for name,value in [('default-boolean',True),('default-list',[]),('default-object',{}),
                       ('default-nul','\0'),('default-control','\x1c'),
                       ('default-outer-nbsp','\xa0model/default\xa0')]:
        rows.append(_case(name,{'default_model':value},None,None,None,None))
    rows.extend([
        _case('env-control',{},'\x1c',None,None,None),
        _case('stored-nul',{},None,'\0',None,None),
        _case('empty-inline',{},None,None,'',None),
        _case('sidecar-zero',{},None,None,None,0),
        _case('sidecar-negative',{},None,None,None,-1),
        _case('null-meta',{},None,None,None,None,null_marker=True,doc_space='9'),
    ])
    return rows


def policy_prompts()->list[str]:
    return [
        LEGACY,'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
        'minishlab/potion-code-16M-v2','ken/static-qwen3-r512-v2','unknown/model','',
        'Qwen/Qwen3-Embedding','Qwen/Qwen3-Embedding-0.6B','Qwen/Qwen3-EmbeddingX',
        'Qwen/Qwen3-Embedding/é','qwen/Qwen3-Embedding-0.6B',
        'prefix/Qwen/Qwen3-Embedding-0.6B',' Qwen/Qwen3-Embedding-0.6B',
        'intfloat/multilingual-e5','intfloat/multilingual-e5-large',
        'intfloat/multilingual-e5X','intfloat/e5','intfloat/e5-base',
        'intfloat/e5-base/é','INTFLOAT/e5-base','prefix/intfloat/e5-base',
        'intfloat/e4-base','intfloat/e5\0',
    ]


_CHILD=r'''
import hashlib,json,os,platform,sys,tempfile,unicodedata
from pathlib import Path
import ken.embedder as emb
from ken import db
import ken._paths as paths
request=json.load(sys.stdin);reference=Path(request['reference']).resolve()
sources={}
for relative,module in [('src/ken/embedder/__init__.py',emb),('src/ken/db.py',db),
                        ('src/ken/_paths.py',paths)]:
 path=Path(module.__file__).resolve()
 if path!=reference/relative:raise ValueError('original policy import escaped frozen tree')
 sources[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
if unicodedata.unidata_version!='15.0.0':raise ValueError('original Unicode15 required')
results=[];observations=[]
with tempfile.TemporaryDirectory(prefix='original-model-policy-') as directory:
 project=Path(directory)/'project';internal=project/'.ken';internal.mkdir(parents=True)
 marker=internal/'meta.json';conn=db.connect(internal/'ken.db')
 conn.executescript('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);'
                   'CREATE TABLE ci_files(path TEXT PRIMARY KEY,embedding BLOB,vec_slot INTEGER);')
 config=Path(os.environ['KEN_CONFIG_DIR'])/'config.json'
 old_cwd=Path.cwd();os.chdir(project)
 def metadata():return {r['key']:r['value'] for r in conn.execute('SELECT key,value FROM meta ORDER BY key')}
 def logical_rows():
  return (tuple(tuple(r) for r in conn.execute('SELECT key,value FROM meta ORDER BY key')),
          tuple(tuple(r) for r in conn.execute('SELECT path,embedding,vec_slot FROM ci_files ORDER BY path')))
 try:
  for case in request['cases']:
   data=case['input'];setup=case['source_setup'];facts=data['facts'];emb.reset_embedder()
   if data['environment'] is None:os.environ.pop('KEN_EMBED_MODEL',None)
   else:os.environ['KEN_EMBED_MODEL']=data['environment']
   config.write_text(json.dumps(data['user_config']),encoding='utf-8')
   if data['project_visible']:marker.write_text('{}',encoding='utf-8')
   else:marker.unlink(missing_ok=True)
   conn.execute('DELETE FROM ci_files');conn.execute('DELETE FROM meta')
   conn.execute('INSERT INTO meta VALUES (?,?)',('unrelated','keep'))
   conn.execute('INSERT INTO meta VALUES (?,?)',('embed_doc_space',setup['document_space']))
   if facts['recorded_model'] is not None or setup['null_recorded_marker']:
    conn.execute('INSERT INTO meta VALUES (?,?)',('embed_model',facts['recorded_model']))
   encoded=setup['embedding_hex'];blob=bytes.fromhex(encoded) if encoded is not None else None
   conn.execute('INSERT INTO ci_files VALUES (?,?,?)',('fixture.py',blob,setup['vec_slot']))
   if emb._has_embeddings(conn)!=facts['file_vectors_present']:
    raise ValueError('declared file-vector fact differs from actual original rows')
   before_rows=logical_rows();before_meta=metadata()
   recommended=emb.recommended_model();model=emb.resolve_model(conn);upgrade=emb.pending_upgrade(conn)
   active=[]
   for forced in data['forced_variants']:
    emb.reset_embedder()
    if forced is not None:emb.configure_embedder(forced)
    active.append(emb.active_model())
   unchanged=logical_rows()==before_rows
   configured=emb.configure_for_project(conn);after=metadata()
   if configured!=model:raise ValueError('original configure and resolve disagree')
   delta={k:v for k,v in after.items() if k not in before_meta or before_meta[k]!=v}
   pin=None
   if 'embed_model' in delta:
    pin={'model':after['embed_model'],'document_space':int(after['embed_doc_space'])}
   results.append({'id':case['id'],'recommended':recommended,
    'project':{'model':model,'initial_pin':pin},'active':active,
    'upgrade':None if upgrade is None else {'current':upgrade[0],'recommended':upgrade[1]}})
   observations.append({'id':case['id'],'selection_preserves_rows':unchanged,
    'encoder_singleton_unloaded':emb._singleton is None,'metadata_before':before_meta,
    'metadata_after':after,'pin_delta':delta})
   if not unchanged or emb._singleton is not None:
    raise ValueError('selection changed rows or instantiated an encoder')
 finally:
  conn.close();emb.reset_embedder();os.chdir(old_cwd)
prompts=[]
for model in request['prompts']:
 query,passage=emb.prompts_for(model)
 prompts.append({'model':model,'query':query,'passage':passage,'asymmetric':emb.is_asymmetric(model)})
print(json.dumps({'scope':'original-model-policy/1','platform':platform.system(),
 'architecture':platform.machine(),'oracle':{'frozen_import':True,'unicode':unicodedata.unidata_version,
 'python':platform.python_version(),'sources':sources},'results':results,
 'observations':observations,'prompts':prompts},ensure_ascii=True,allow_nan=False))
'''


def capture_policy(reference:Reference,out:Path)->dict:
    if verify_reference(reference.root,reference.manifest_path):
        raise ValueError('frozen source drift')
    request={'reference':str(reference.root),'cases':policy_cases(),'prompts':policy_prompts()}
    out=out.resolve();out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ken-model-policy-reference-') as directory:
        sandbox=Path(directory)
        result=subprocess.run([str(reference.python),'-c',_CHILD],
            input=json.dumps(request,ensure_ascii=True,allow_nan=False),
            cwd=sandbox,env=reference_env(reference,sandbox/'environment'),
            text=True,capture_output=True,timeout=120)
    out.with_suffix('.stderr.log').write_text(result.stderr)
    if result.returncode or result.stderr:
        raise ValueError(f'original policy capture failed: {result.stderr}')
    if verify_reference(reference.root,reference.manifest_path):
        raise ValueError('frozen source drift')
    data=json.loads(result.stdout);data['reference_fingerprint']=reference.fingerprint
    out.write_text(json.dumps(data,indent=2,ensure_ascii=True,allow_nan=False)+'\n')
    return data
