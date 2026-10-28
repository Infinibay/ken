"""Independent new source-preparation/cache histories, without original pytest."""
from pathlib import Path
import gzip,hashlib,json,subprocess,sys
from .reference import Reference,reference_env
from .execution_profiles import authenticate_frozen,FP
from .native_json import load
FIXTURE='crates/ken-retrieval/tests/fixtures/context-preparation-reference.json.gz'
API_SHA='4e5cf87deef44fcdeb4020929d9e6f57c464868fc251338beed7461188f51ea8'
def cases():
    source='''class Reader:
    def read(self,value):
        return value or load()
def store(key,value):
    mapping[key]=value
'''
    rows=[]
    def prep(name,*,files=None,actions=None):
        rows.append(dict(id=name,kind='prepare',files=files if files is not None else {'pkg/reader.py':source},actions=actions or [dict(op='prepare',generation=7),dict(op='prepare',generation=8)]))
    def cache(name,actions):rows.append(dict(id=name,kind='cache',actions=actions))
    prep('cold-warm-generation')
    prep('unicode-ascii-owner-order',files={'z.py':'def z():\n    return 1\n','é.py':'def café():\n    return "é🚀"\n','a.py':'def a():\n    return 2\n','🚀.py':'def rocket():\n    return 3\n'})
    prep('comment-only-dedup',files={'pkg/__init__.py':'# source-only note\n'})
    prep('long-documentation-codepoints',files={'long.py':'def documented():\n    """'+('é🚀'*450)+'"""\n    return 1\n'})
    prep('multiple-files',files={'b.py':source,'a.py':source})
    prep('empty-catalog',files={})
    prep('warm-with-unavailable-encoder',actions=[dict(op='prepare',generation=7),dict(op='encoder',mode='error'),dict(op='prepare',generation=8)])
    prep('vector-cache-rebuild-with-unavailable-encoder',actions=[dict(op='prepare',generation=7),dict(op='clear_snapshots'),dict(op='encoder',mode='error'),dict(op='prepare',generation=8)])
    prep('immutable-catalog-after-disk-edit',actions=[dict(op='prepare',generation=7),dict(op='disk_edit'),dict(op='prepare',generation=8)])
    for target in ('identity','manifest-fields','full.npy','views.npy'):
        prep('corrupt-'+target,actions=[dict(op='prepare',generation=7),dict(op='corrupt',target=target),dict(op='prepare',generation=8)])
    for mode in ('zero','nan','short','error'):
        prep('encoder-'+mode,actions=[dict(op='encoder',mode=mode),dict(op='prepare',generation=7)])
    for mode in ('zero','short'):
        prep('corrupt-cache-'+mode,actions=[dict(op='prepare',generation=7),dict(op='corrupt_cache',mode=mode),dict(op='clear_snapshots'),dict(op='prepare',generation=8)])
    put=lambda text,mode='unit':dict(op='put',text=text,mode=mode)
    get=lambda text:dict(op='get',text=text)
    cache('cache-missing-and-reopen',[get('missing'),put('alpha'),get('alpha'),dict(op='reopen'),get('alpha')])
    cache('cache-conflict-keeps-first',[put('alpha'),dict(op='put',text='alpha',mode='unit',index=2),get('alpha')])
    cache('cache-unicode-text',[put('é🚀\ntext'),get('é🚀\ntext')])
    cache('cache-model-isolation',[put('alpha'),dict(op='model',name='other'),get('alpha'),put('alpha'),dict(op='model',name='base'),get('alpha')])
    cache('cache-text-collision',[put('alpha'),dict(op='collision',text='alpha'),get('alpha')])
    for mode in ('zero','nan','short','near-unit'):
        cache('cache-'+mode,[put('alpha',mode),get('alpha')])
    cache('cache-transaction-rollback',[put('prior'),dict(op='put_many',items=[dict(text='alpha',mode='unit'),dict(text='bad',mode='zero')]),get('alpha'),get('prior')])
    return rows
SCRIPT=r'''
import dataclasses,hashlib,importlib.metadata,json,pathlib,platform,shutil,sqlite3,sys
import numpy as np
import ken.retrieval.context_preparation as original
from ken.embedder.contextual_onnx import ContextModel
from ken.model_assets import ModelAssets
from ken.retrieval.profile import EncoderSpec
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
def sha(data):return hashlib.sha256(data).hexdigest()
def file_id(p):return dict(bytes=p.stat().st_size,sha256=sha(p.read_bytes()))
def vector(mode='unit',index=0):
 value=np.zeros(767 if mode=='short'else 768,dtype=np.float32)
 value[index]=float('nan')if mode=='nan'else 0. if mode=='zero'else .99999 if mode=='near-unit'else 1.
 return value
class Encoder:
 def __init__(self,definition):
  self.model=ContextModel(ModelAssets.from_dict(definition),definition['query_prefix'],definition['document_projection']);self.spec=self.model.spec;self.calls=[];self.mode='basis'
 def embed_passages(self,texts):
  self.calls.append(list(texts))
  if self.mode=='error':raise ValueError('encoder unavailable')
  return np.asarray([vector(self.mode if self.mode!='basis'else'unit',hashlib.sha256(t.encode()).digest()[0]) * (2. if self.mode=='basis'else 1.)for t in texts])
def matrix(value):return dict(shape=list(value.shape),dtype=str(value.dtype),sha256=sha(value.tobytes()),readonly=not value.flags.writeable)
def state(directory):
 database=directory/'vectors.db';cache=[]
 if database.exists():
  with sqlite3.connect(database)as conn:
   cache=[dict(model=m,hash=h,text=t,vector_sha256=sha(v),vector_bytes=len(v))for m,h,t,v in conn.execute('SELECT model,hash,text,vector FROM vectors ORDER BY model,hash')]
 snapshots={p.name:{f.name:file_id(f)for f in sorted(p.iterdir())if f.is_file()}for p in sorted((directory/'snapshots').glob('*'))if p.is_dir()and not p.name.startswith('prepare-')}
 return dict(cache=cache,snapshots=snapshots,temporary_count=len(list((directory/'snapshots').glob('prepare-*'))))
records=[]
for case in request['cases']:
 home=pathlib.Path(request['catalog_root'])/case['id'];home.mkdir(parents=True);directory=home/'cache';encoder=Encoder(request['definition'])
 data=dict(kind=case['kind'],model_registration=request['definition'],actions=case['actions'])
 if case['kind']=='prepare':
  catalog=make_catalog(home/'source',case['files'])
  data['physical']=dict(files={p:list(s.encode())for p,s in case['files'].items()},owners=[dict(key=dataclasses.asdict(k),passages=[dataclasses.asdict(p)for p in passages])for k,passages in catalog.owners.items()])
 else:store=original.ContextVectorCache(directory,encoder.spec)
 events=[]
 for action in case['actions']:
  encoder.calls=[];row={}
  try:
   op=action['op']
   if op=='prepare':
    result=original.prepare_context(catalog,action['generation'],encoder,directory);full=result.vectors;views=result.source_views
    row['result']=dict(generation=full.generation,owners=[dataclasses.asdict(k)for k in full.owners],hashes=list(full.source_hashes),model=dataclasses.asdict(full.model),view_model=dataclasses.asdict(views.model),full=matrix(full.matrix),pool=matrix(views.matrix),rows={n:v.tolist()for n,v in views.rows.items()},mapped_views=isinstance(views.matrix,np.memmap))
   elif op=='encoder':encoder.mode=action['mode'];row['result']=None
   elif op=='clear_snapshots':shutil.rmtree(directory/'snapshots');row['result']=None
   elif op=='disk_edit':next((home/'source').rglob('*.py')).write_text('changed after catalog construction\n');row['result']=None
   elif op=='corrupt':
    destination=next((directory/'snapshots').iterdir());target=action['target']
    if target in ('identity','manifest-fields'):
     p=destination/'manifest.json';v=json.loads(p.read_bytes())
     if target=='identity':v['identity_sha256']='0'*64
     else:del v['artifacts']['views.npy']
     p.write_text(json.dumps(v,sort_keys=True))
    else:(destination/target).write_bytes(b'corrupt')
    row['result']=None
   elif op=='corrupt_cache':
    with sqlite3.connect(directory/'vectors.db')as conn:conn.execute('UPDATE vectors SET vector=?',(vector(action['mode']).tobytes(),))
    row['result']=None
   elif op=='get':
    value=store.get(action['text']);row['result']=None if value is None else dict(bytes=value.nbytes,sha256=sha(value.tobytes()))
   elif op=='put':store.put(action['text'],vector(action['mode'],action.get('index',0)));row['result']=None
   elif op=='put_many':store.put_many((i['text'],vector(i['mode']))for i in action['items']);row['result']=None
   elif op=='reopen':store.__exit__();store=original.ContextVectorCache(directory,encoder.spec);row['result']=None
   elif op=='model':
    store.__exit__();model=encoder.spec if action['name']=='base'else dataclasses.replace(encoder.spec,model_id=encoder.spec.model_id+'/other');store=original.ContextVectorCache(directory,model);row['result']=None
   elif op=='collision':
    with store.conn:store.conn.execute('UPDATE vectors SET text=? WHERE model=? AND hash=?',('foreign',store.model,sha(action['text'].encode())))
    row['result']=None
   else:raise ValueError('unknown observation action')
  except Exception as error:row['error']=dict(type=type(error).__name__,message=str(error))
  row.update(calls=encoder.calls,state=state(directory));events.append(row)
 if case['kind']=='cache':store.__exit__()
 record=dict(id=case['id'],input=data,events=events);records.append(record)
 with (pathlib.Path(request['result']).parent/'records.jsonl').open('a')as stream:stream.write(json.dumps(record,ensure_ascii=True)+'\n')
value=dict(format='ken-context-preparation-reference/1',cases=records,definition=request['definition'],original_source_sha256=sha(pathlib.Path(original.__file__).read_bytes()),runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),numpy=np.__version__,sqlite=sqlite3.sqlite_version,onnxruntime=importlib.metadata.version('onnxruntime'),tokenizers=importlib.metadata.version('tokenizers')))
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def digest(value):return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-context-preparation-reference/1','format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'observer differs')
        require(value['reference_fingerprint']==FP and value['original_source_sha256']==API_SHA,'original source differs')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9',numpy='2.4.4',sqlite='3.47.1',onnxruntime='1.25.1',tokenizers='0.22.2'),'runtime differs')
        definition=load(Path(__file__).resolve().parents[2]/'crates/ken-models/resources/code-context-int8.json');require(value['definition']==definition,'registration differs')
        require(value['inputs_sha256']==hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest(),'case definitions differ')
        require([c['id']for c in value['cases']]==[c['id']for c in cases()],'case inventory differs')
        for row,case in zip(value['cases'],cases(),strict=True):
            data=row['input'];required={'kind','model_registration','actions'}|({'physical'}if case['kind']=='prepare'else set())
            require(set(data)==required and data['kind']==case['kind']and data['model_registration']==definition and data['actions']==case['actions'],'case inputs differ')
            if case['kind']=='prepare':
                require(set(data['physical'])=={'files','owners'}and data['physical']['files']=={p:list(s.encode())for p,s in case['files'].items()},'physical inputs differ')
                for owner in data['physical']['owners']:
                    key=owner['key'];require(key['path']in data['physical']['files']and bool(owner['passages']),'owner input differs')
                    for passage in owner['passages']:require(passage['entity']==key and passage['source_hash']==hashlib.sha256(bytes(data['physical']['files'][key['path']])).hexdigest(),'source binding differs')
            require(len(row['events'])==len(case['actions']),'action observations differ')
            if row['id']=='cold-warm-generation':require(bool(row['events'][0]['calls'])and not row['events'][1]['calls'],'cold/warm source calls differ')
        require(value['observations_sha256']==digest(value),'observations differ');return[]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def capture(reference:Reference,out:Path):
    if out.exists():raise FileExistsError(out)
    authenticate_frozen(reference);out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    definition=load(Path(__file__).resolve().parents[2]/'crates/ken-models/resources/code-context-int8.json')
    request=dict(reference=str(reference.root),cases=cases(),catalog_root=str(out/'catalogs'),result=str(out/'observations.json'),definition=definition)
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    child=subprocess.run([str(Path(sys.executable).absolute()),'-B',str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=300)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError(child.stderr.decode(errors='replace'))
    authenticate_frozen(reference);value=load(out/'observations.json');value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=FP,inputs_sha256=hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest());value['observations_sha256']=digest(value)
    if errors:=validate_reference(value):raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value
