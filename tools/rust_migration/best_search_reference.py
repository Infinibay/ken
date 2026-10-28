"""New complete original BestSearch histories with explicit model execution leaves."""
from pathlib import Path
import gzip,hashlib,json,subprocess,sys
from .reference import Reference,reference_env
from .execution_profiles import authenticate_frozen,FP
from .native_json import load
FIXTURE='crates/ken-retrieval/tests/fixtures/best-search-reference.json.gz'
API_SHA='c08e04305fdff68281e9239951bfc707f9bc95c6923b91889a19a1e98b2947bf'
def cases():
    source='''class Reader:
    def read(self, value):
        return value or load()
def store(key,value):
    mapping[key]=value
def wrapper(error):
    return str(error)
def annotate(error):
    raise AttributeError("location") from error
'''
    rows=[]
    def project(name='p0',files=None,seed='source',databases=None):
        files=files if files is not None else {'pkg/reader.py':source}
        return dict(id=name,files=files,seed=seed,databases=databases or {'main':list(files)})
    def search(query='Where is a mapping changed?',project='p0',database='main',**options):return dict(op='search',project=project,database=database,request=dict(query=query,**options))
    def prepare(project='p0',database='main'):return dict(op='prepare',project=project,database=database)
    def add(name,actions,projects=None,models='controlled',expansion=None,controls=None):rows.append(dict(id=name,projects=projects if projects is not None else [project()],actions=actions,models=models,expansion=expansion or {},controls=controls or {}))
    add('empty-source',[search(),prepare()],projects=[project(files={})])
    add('unindexed-files-are-not-discovered',[search(),prepare()],projects=[project(seed='none')])
    add('bootstrap-old-source-index',[search('Reader'),search('store'),search('Reader',target='file')],projects=[project(seed='files-only')])
    for name,query,options in [('class','Reader',{}),('callable','store',{}),('qualified','pkg/reader.py::Reader.read',{}),('file','Reader',dict(target='file')),('explicit-symbol-class','Reader',dict(piece_kind='symbol')),('explicit-class-callable','store',dict(piece_kind='class')),('module','Reader',dict(piece_kind='module'))]:add('cold-exact-'+name,[search(query,**options)])
    for name,files,query in [('enum',{'mode.rs':'enum Mode {\n    Read,\n    Write,\n}\n'},'Mode'),('struct',{'record.rs':'struct Record {\n    value: i32,\n}\n'},'Record'),('interface',{'Reader.java':'interface Reader {\n    int read();\n}\n'},'Reader')]:add('cold-declaration-'+name,[search(query),search(query,target='file')],projects=[project(files=files)])
    add('ambiguous-exact-names',[search('Reader',explain=True)],projects=[project(files={'a.py':source,'b.py':source})])
    for kind in ('class','module','file','symbol'):add('contextual-'+kind,[search(piece_kind=kind,explain=True),search(piece_kind=kind,limit=1)])
    add('original-query-policies',[search('Preserve the exception cause',explain=True)],expansion={'Preserve the exception cause':'Find an AND expression'})
    add('expanded-query-does-not-grant-exact',[search('Find the component that changes state',explain=True)],expansion={'Find the component that changes state':'Reader'})
    add('named-path',[search('Find `pkg/reader.py`',piece_kind='file',explain=True)])
    add('display-budget',[search(max_chars=650,explain=True),search(max_chars=1400,explain=True)])
    add('prepare-and-reuse',[prepare(),search(),prepare(),search()])
    add('empty-prepare-after-resources',[search(),prepare(project='empty')],projects=[project(),project('empty',files={})])
    add('generation-source-change',[search(),dict(op='write',project='p0',path='pkg/reader.py',text=source.replace('mapping[key]=value','mapping[key]=transform(value)')),dict(op='reindex',project='p0',database='main'),search(),search()])
    add('unchanged-source-profile-repair',[search(),dict(op='corrupt_profile',project='p0',database='main'),search()])
    add('source-extractor-refresh',[search(),dict(op='old_extractor',project='p0',database='main'),search()])
    add('stale-disk-presentation',[search(),dict(op='write',project='p0',path='pkg/reader.py',text='# replaced after preparation\n'),search()])
    add('same-root-two-databases',[search(database='left'),search(database='right'),search(database='left')],projects=[project(files={'a.py':source,'b.py':source.replace('mapping[key]=value','other[key]=value')},databases={'left':['a.py'],'right':['b.py']})])
    add('prepared-project-lru-two',[search(project='a'),search(project='b'),search(project='a'),search(project='c'),search(project='b')],projects=[project('a'),project('b'),project('c')])
    add('resource-failure-retry',[search(),search()],controls={'resource_failures':1})
    add('context-preparation-failure-retry',[search(),dict(op='context_mode',mode='basis'),search()],controls={'context_mode':'error'})
    add('neural-failure-retains-prepared-project',[search(),dict(op='neural_mode',mode='length'),search()],controls={'neural_mode':'error'})
    add('expansion-failure-retry',[search(),dict(op='expansion_mode',mode='normal'),search()],controls={'expansion_mode':'error'})
    for kind,query in [('symbol','Preserve the exception cause'),('class','Which class reads values?'),('file','Where is a mapping changed?')]:add('registered-'+kind,[search(query,piece_kind=kind,explain=True),search(query,piece_kind=kind,limit=1)],models='registered')
    return rows
SCRIPT=r'''
import dataclasses,functools,hashlib,importlib.metadata,json,pathlib,platform,sqlite3,sys
import numpy as np
import ken.retrieval.best_search as original
import ken.retrieval.best_resources as resource_module
from ken.db import connect,init_schema
from ken.indexer import index_files
from ken.model_assets import ModelAssets
from ken.embedder.contextual_onnx import code_context_model
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import potion_profile,_backend_runtime,ContextualRetrieval,EvidenceRanking
from ken.retrieval.piece_ranking import PieceReranker,PIECE_FEATURES
from ken.retrieval.owner_ranking import EvidenceReranker,FEATURES,CONTEXTUAL_FEATURES,SOURCE_VIEW_FEATURES
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.indexing import index_project
from ken.retrieval.passages import PassagePolicy
from ken.retrieval.source_views import SOURCE_VIEW_PROJECTION
from dataclasses import replace
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
original_resolve=ModelAssets.resolve
sources={(v['model_id'],v['revision']):pathlib.Path(request['sources'][name])for name,v in [('potion',request['registrations']['potion']),('context',request['registrations']['context']),('ettin',request['registrations']['ettin']['source'])]}
def source_override(self,*args,**kwargs):
 key=(self.model_id,self.revision)
 if key not in sources:raise ValueError('explicit registered source override required: '+self.model_id)
 return self.verify(sources[key])
ModelAssets.resolve=source_override
legacy=dict(format='ken-legacy-runtime/1',backends={name:_backend_runtime(name)for name in ('static','model2vec','sentence-transformers','mlx','provided')},evidence=[(p,importlib.metadata.version(p))for p in ('numpy','snowballstemmer')],contextual=[(p,importlib.metadata.version(p))for p in ('numpy','tokenizers','onnxruntime')])
real_default=resource_module.default_resources
class Words:
 def __init__(self,control,real=None):self.control,self.real=control,real;self.spec=real.spec if real is not None else potion_profile().identity
 def embed_query(self,text):
  self.control.calls.append(dict(op='word_query',text=text));return self.real.embed_query(text)if self.real is not None else np.asarray([1.,0.,0.,0.],dtype=np.float32)
 def embed_passages(self,texts):
  self.control.calls.append(dict(op='word_passages',texts=list(texts)));return self.real.embed_passages(texts)if self.real is not None else [np.asarray([1.,0.,0.,0.],dtype=np.float32)for _ in texts]
 def token_count(self,text):
  if self.real is not None:return self.real.token_count(text)
  from ken.retrieval.tokenization import code_tokens
  return len(code_tokens(text))
class Context:
 def __init__(self,control,real=None):self.control,self.real=control,real;self.model=real.model if real is not None else code_context_model();self.spec=self.model.spec
 def value(self,text):
  vector=np.zeros(768,dtype=np.float32);vector[hashlib.sha256(text.encode()).digest()[0]]=2.;return vector
 def embed_query(self,text):
  self.control.calls.append(dict(op='context_query',text=text));return self.real.embed_query(text)if self.real is not None else self.value(text)
 def embed_passages(self,texts):
  self.control.calls.append(dict(op='context_passages',texts=list(texts)))
  if self.control.context_mode=='error':raise ValueError('context encoder unavailable')
  return self.real.embed_passages(texts)if self.real is not None else [self.value(t)for t in texts]
class Neural:
 def __init__(self,control,real=None):self.control,self.real=control,real
 def pair_fits(self,q,t):self.control.calls.append(dict(op='pair_fits',query=q,text=t));return self.real.pair_fits(q,t)if self.real is not None else len(q)+len(t)<=10000
 def score(self,q,texts):
  self.control.calls.append(dict(op='neural_score',query=q,texts=list(texts)))
  if self.control.neural_mode=='error':raise ValueError('neural unavailable')
  return self.real.score(q,texts)if self.real is not None else ([float(len(t)%19-9)/4 for t in texts],dict(model='controlled-best-search',documents=len(texts)))
class Control:
 def __init__(self,case):
  self.case=case;self.calls=[];self.resource_failures=case['controls'].get('resource_failures',0);self.context_mode=case['controls'].get('context_mode','basis');self.neural_mode=case['controls'].get('neural_mode','length');self.expansion_mode=case['controls'].get('expansion_mode','normal');self.resources=None
  self.words=Words(self);self.context=Context(self)
  self.native=NumericRanker.from_dict(dict(schema=1,features=[*FEATURES,*CONTEXTUAL_FEATURES,*SOURCE_VIEW_FEATURES],trees=[dict(value=0.)]));self.piece=NumericRanker.from_dict(dict(schema=1,features=PIECE_FEATURES,trees=[dict(value=0.)]))
  self.expansion_revision=hashlib.sha256(json.dumps(case['expansion'],sort_keys=True).encode()).hexdigest()
 def expanded(self,q,real=None):
  self.calls.append(dict(op='expand',query=q))
  if self.expansion_mode=='error':raise ValueError('expansion unavailable')
  return real(q)if real is not None else self.case['expansion'].get(q,q)
 @functools.lru_cache(maxsize=1)
 def get(self):
  self.calls.append(dict(op='build_resources'))
  if self.resource_failures:
   self.resource_failures-=1;raise ValueError('resources unavailable')
  if self.case['models']=='registered':
   real_default.cache_clear();r=real_default();self.words=Words(self,r.words);self.context=Context(self,r.context);neural=Neural(self,r.neural)
   r.owner_ranker.encoder=self.words;r.piece_ranker.encoder=self.words;expand=r.owner_ranker.expand_query;r.owner_ranker.expand_query=lambda q:self.expanded(q,expand)
   self.resources=replace(r,words=self.words,context=self.context,neural=neural);return self.resources
  owner=EvidenceReranker(self.native,self.words,expand_query=self.expanded,expansion_revision=self.expansion_revision)
  view=replace(self.context.model,document_projection=SOURCE_VIEW_PROJECTION).spec
  profile=replace(potion_profile(),contextual=ContextualRetrieval(self.context.spec,view_model=view),evidence=EvidenceRanking(self.native.fingerprint,self.words.spec,self.expansion_revision,feature_version=3,evidence_version=3))
  self.resources=resource_module.SearchResources(self.words,self.context,owner,PieceReranker(self.piece,self.words,stem_words=owner.stem_words),Neural(self),profile);return self.resources
 def config(self):
  if self.case['models']=='registered':
   native,piece=resource_module.load_rank_models();from ken.retrieval.translation_preparation import default_query_expansion
   expansion_revision=default_query_expansion().revision
  else:native,piece,expansion_revision=self.native,self.piece,self.expansion_revision
  view=replace(self.context.model,document_projection=SOURCE_VIEW_PROJECTION).spec
  profile=replace(potion_profile(),contextual=ContextualRetrieval(self.context.spec,view_model=view),evidence=EvidenceRanking(native.fingerprint,self.words.spec,expansion_revision,feature_version=3,evidence_version=3))
  return dict(kind=self.case['models'],base_profile=potion_profile().to_dict(),profile=profile.to_dict(),legacy_runtime=legacy,expansion=self.case['expansion'],controls=self.case['controls'],native_model=native.to_dict()if self.case['models']=='controlled'else None,piece_model=piece.to_dict()if self.case['models']=='controlled'else None,context_registration=request['registrations']['context'],expansion_revision=expansion_revision)
def state(projects,connections,control):
 databases=[]
 for (project,name),conn in connections.items():
  from ken.retrieval.storage import generation
  counts={table:int(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0])for table in ('ci_files','ci_passages','ci_passage_vectors','ci_retrieval_embeddings')}
  fp=conn.execute("SELECT value FROM meta WHERE key='retrieval_profile_fingerprint'").fetchone()
  databases.append(dict(project=project,database=name,generation=generation(conn),counts=counts,profile_fingerprint=None if fp is None else fp[0]))
 cache=[]
 for (source,database,generation,profile),prepared in original._projects.items():
  name=next(name for name,path in projects.items()if str(path.resolve())==source)
  db=next(db for (p,db),conn in connections.items()if p==name and str(conn.execute('PRAGMA database_list').fetchone()[2])==database)
  cache.append(dict(project=name,database=db,generation=generation,profile_fingerprint=profile,descriptions=len(prepared.pieces.descriptions)))
 return dict(databases=databases,prepared=cache)
records=[]
for case in request['cases']:
 home=pathlib.Path(request['catalog_root'])/case['id'];home.mkdir(parents=True);original._projects.clear();real_default.cache_clear();control=Control(case);original.default_resources=control.get;projects={};connections={}
 for project in case['projects']:
  name=project['id'];path=home/name;path.mkdir();projects[name]=path
  for filename,text in project['files'].items():p=path/filename;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
  for db,files in project['databases'].items():
   conn=connect(path/(db+'.db'));init_schema(conn);connections[name,db]=conn
   if project['seed']!='none':index_files(conn,path,[pathlib.Path(f)for f in files],retrieval_policy=PassagePolicy())
   if project['seed']=='files-only':
    with conn:conn.execute('DELETE FROM ci_passages');conn.execute('DELETE FROM ci_retrieval_files')
 config=control.config();data=dict(projects=case['projects'],actions=case['actions'],models=config);events=[]
 for action in case['actions']:
  control.calls=[];row={}
  try:
   op=action['op']
   if op in ('search','prepare','reindex','corrupt_profile','old_extractor'):
    path=projects[action['project']];conn=connections[action['project'],action['database']]
   if op=='search':row['result']=original.search_best(conn,path,SearchRequest(**action['request'])).to_dict()
   elif op=='prepare':row['result']=original.prepare_best(conn,path)
   elif op=='write':
    p=projects[action['project']]/action['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_text(action['text']);row['result']=None
   elif op=='reindex':
    r=control.get();files=[pathlib.Path(r[0])for r in conn.execute('SELECT path FROM ci_files ORDER BY path')];index_project(conn,path,files,profile=potion_profile(),encoders={'identity':r.words,'behavior':r.words});row['result']=None
   elif op=='corrupt_profile':
    with conn:conn.execute("UPDATE meta SET value=? WHERE key='retrieval_profile_fingerprint'",('0'*64,))
    row['result']=None
   elif op=='old_extractor':
    with conn:conn.execute('UPDATE ci_retrieval_files SET extractor_version=0')
    row['result']=None
   elif op=='context_mode':control.context_mode=action['mode'];row['result']=None
   elif op=='neural_mode':control.neural_mode=action['mode'];row['result']=None
   elif op=='expansion_mode':control.expansion_mode=action['mode'];row['result']=None
   else:raise ValueError('unknown history action')
  except Exception as error:row['error']=dict(type=type(error).__name__,message=str(error).replace(str(home),'$CASE'))
  row.update(calls=control.calls,state=state(projects,connections,control));events.append(row)
 record=dict(id=case['id'],input=data,events=events);records.append(record)
 with (pathlib.Path(request['result']).parent/'records.jsonl').open('a')as stream:stream.write(json.dumps(record,ensure_ascii=True)+'\n')
 for conn in connections.values():conn.close()
 original._projects.clear();real_default.cache_clear()
value=dict(format='ken-best-search-reference/1',cases=records,registrations=request['registrations'],runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),sqlite=sqlite3.sqlite_version,packages={p:importlib.metadata.version(p)for p in ('numpy','model2vec','tokenizers','safetensors','onnxruntime','snowballstemmer','ctranslate2','sentencepiece')}),original_source_sha256=hashlib.sha256(pathlib.Path(original.__file__).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
# Retained observer identity for paths that never reached its broken controlled tokenizer.
ATTEMPT_SCRIPT=SCRIPT.replace("from ken.retrieval.tokenization import code_tokens\n  return len(code_tokens(text))","from ken.retrieval.tokenization import count_code_tokens\n  return count_code_tokens(text)")
def digest(value):return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def registrations(repo):return {name:load(repo/'crates/ken-models/resources'/filename)for name,filename in [('potion','potion-code-16M-v2.json'),('context','code-context-int8.json'),('ettin','ettin-68m-fp32.json')]}
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-best-search-reference/1','format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'observer differs')
        require(value['reference_fingerprint']==FP and value['original_source_sha256']==API_SHA,'original source differs')
        require(value['registrations']==registrations(Path(__file__).resolve().parents[2]),'registered models differ')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9',sqlite='3.47.1',packages=dict(numpy='2.4.4',model2vec='0.9.0',tokenizers='0.22.2',safetensors='0.8.0',onnxruntime='1.25.1',snowballstemmer='3.0.1',ctranslate2='4.8.2',sentencepiece='0.2.1')),'runtime differs')
        require(value['inputs_sha256']==hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest(),'input definitions differ')
        require([c['id']for c in value['cases']]==[c['id']for c in cases()],'case inventory differs')
        for row,case in zip(value['cases'],cases(),strict=True):
            data=row['input'];require(set(data)=={'projects','actions','models'}and data['projects']==case['projects']and data['actions']==case['actions'],'history inputs differ')
            require(data['models']['kind']==case['models']and data['models']['expansion']==case['expansion']and data['models']['controls']==case['controls'],'model leaves differ')
            require(len(row['events'])==len(case['actions']),'history observations differ')
            if case['id'].startswith(('cold-','empty-source','bootstrap-','unindexed-')):require(all(not e['calls']for e in row['events']),'cold route loaded resources')
        allowed={'resource-failure-retry':{0:'resources unavailable'},'context-preparation-failure-retry':{0:'context encoder unavailable'},'neural-failure-retains-prepared-project':{0:'neural unavailable'},'expansion-failure-retry':{0:'expansion unavailable'},'source-extractor-refresh':{2:'source extraction policy changed; prepare the search index again'}}
        for row in value['cases']:
            expected=allowed.get(row['id'],{})
            require({i:e['error']['message']for i,e in enumerate(row['events'])if 'error'in e}==expected,row['id']+': unexpected endpoint failure')
            if row['id'].startswith('registered-'):
                require(all(bool(e.get('result',{}).get('results'))for e in row['events']),'missing real endpoint results')
                require(all(any(c['op']==op for e in row['events']for c in e['calls'])for op in ('word_passages','context_passages','neural_score')),'missing actual model composition')
        parts=value['observer_parts'];seen=[]
        old_ids=[c['id']for c in cases()if c['id'].startswith(('cold-','registered-','bootstrap-','unindexed-','empty-source'))]
        for part in parts:
            require(set(part)=={'script_sha256','case_ids'},'observer partition fields differ')
            if part['script_sha256']==hashlib.sha256(ATTEMPT_SCRIPT.encode()).hexdigest():require(part['case_ids']==old_ids,'unaccepted attempt rows reused')
            else:require(part['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'foreign observer partition')
            seen.extend(part['case_ids'])
        require(sorted(seen)==sorted(c['id']for c in cases())and len(seen)==len(set(seen)),'observer partition differs')
        require(value['observations_sha256']==digest(value),'observations differ');return[]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def capture(reference:Reference,out:Path,*,sources:dict|None=None):
    if out.exists():raise FileExistsError(out)
    authenticate_frozen(reference);out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    repo=Path(__file__).resolve().parents[2]
    if sources is None:
        import os
        sources={name:os.environ[key]for name,key in [('potion','KEN_POTION_SOURCE'),('context','KEN_CONTEXT_SNAPSHOT'),('ettin','KEN_ETTIN_SOURCE')]}
    request=dict(reference=str(reference.root),cases=cases(),catalog_root=str(out/'catalogs'),result=str(out/'observations.json'),registrations=registrations(repo),sources=sources)
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    env=reference_env(reference,out/'environment');env['KEN_CACHE_DIR']=str(out/'model-cache')
    child=subprocess.run([str(Path(sys.executable).absolute()),'-B',str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=env,capture_output=True,timeout=900)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError(child.stderr.decode(errors='replace'))
    authenticate_frozen(reference);value=load(out/'observations.json');value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=FP,inputs_sha256=hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest());value['observations_sha256']=digest(value);value['observer_parts']=[dict(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),case_ids=[c['id']for c in cases()])]
    if errors:=validate_reference(value):raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value
