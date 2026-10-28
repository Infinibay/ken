"""Independent complete PieceSearch observations; never execute original pytest roots."""
from pathlib import Path
import gzip,hashlib,json,subprocess,sys
from .reference import Reference,reference_env
from .execution_profiles import authenticate_frozen,FP
from .native_json import load
FIXTURE='crates/ken-retrieval/tests/fixtures/piece-search-reference.json.gz'
API_SHA='50a4fbee50d37a7509578dfabdfd62c89385b0e61bcca6eec0d99d48f26eff0d'
def cases():
    body='''class Reader:
    def read(self, value):
        return value or load()
    class Inner:
        def invoke(self):
            return action()
def wrapper(error):
    return str(error)
def annotate(error):
    raise AttributeError("location") from error
def logic(a,b):
    return a and b
def test_checks(a,b):
    assert a and b
'''
    files={'pkg/first.py':body,'pkg/second.py':body.replace('location','cause location')}
    names=[['pkg/first.py','wrapper'],['pkg/second.py','annotate'],['pkg/first.py','Reader.read'],['pkg/first.py','Reader.Inner.invoke'],['pkg/second.py','logic'],['pkg/second.py','test_checks']]
    rows=[]
    def add(name,kind='symbol',query='Find code that invokes an action',*,selectors=None,physical=None,expanded=None,exact=False,forest='native-score',disk='unchanged',model=None,**options):
        selected=names if selectors is None else selectors
        rows.append(dict(id=name,files=files if physical is None else physical,selectors=selected,scores=[float(8-i)for i in range(len(selected))],signals=[{'exact':1.}if i==1 else {}for i in range(len(selected))],request=dict(query=query,piece_kind=kind,**options),expanded_query=query if expanded is None else expanded,exact=exact,forest=forest,disk=disk,model=model or dict(kind='controlled',mode='length',pair_budget=10000)))
    for kind in ('class','module','file','symbol'):
        add(kind+'-ordinary',kind)
        add(kind+'-explain',kind,explain=True)
        add(kind+'-exact',kind,exact=True,explain=True)
        add(kind+'-named',kind,query='Find '+kind+' in `pkg/second.py`',explain=True)
        add(kind+'-display-one',kind,limit=1,explain=True)
        add(kind+'-stale',kind,disk='changed',explain=True)
    for budget in (256,650,1400):add('trim-'+str(budget),max_chars=budget,explain=True)
    add('numeric-zero','file',forest='zero',explain=True)
    add('neural-ties','file',model=dict(kind='controlled',mode='zero',pair_budget=10000),explain=True)
    add('original-policy',query='Preserve the exception cause',expanded='Find AND expressions',explain=True)
    add('test-priority',query='Which regression checks AND expressions?',explain=True)
    add('pair-fallback',model=dict(kind='controlled',mode='length',pair_budget=1),explain=True)
    add('pair-error',model=dict(kind='controlled',mode='length',pair_budget=10000,fail_pair=True))
    add('score-error',model=dict(kind='controlled',mode='length',pair_budget=10000,fail_score=True))
    add('empty',selectors=[],explain=True)
    add('duplicates',selectors=[names[0],names[1],names[0],names[2]],explain=True)
    many={f'p{i}.py':f'def run():\n    return {i}\n'for i in range(13)}
    add('native-top10','file',physical=many,selectors=[[p,'run']for p in many],explain=True)
    add('unavailable-class','class',selectors=[names[0],names[1]],explain=True)
    for name,kind,query in [('file','file','Find readers'),('class','class','Which class invokes an action?'),('symbol','symbol','Preserve the exception cause')]:
        add('real-'+name,kind,query,explain=True,model=dict(kind='ettin',options={}))
    for kind in ('class','module','file','symbol'):
        add(kind+'-leading-path',kind,query='Find `pkg/second.py`',explain=True)
    return rows
SCRIPT=r'''
import dataclasses,hashlib,importlib.metadata,json,math,pathlib,platform,sys
import numpy as np
import ken.retrieval.piece_search as original
from ken.retrieval.model import SearchRequest,CodeMatch
from ken.retrieval.piece_ranking import PieceReranker,PIECE_FEATURES
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.neural_assets import prepare_reranker
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
class Words:
 def embed_query(self,text):return np.array([1.,0.],dtype=np.float32)
 def embed_passages(self,texts):return np.array([[1.,0.]for t in texts],dtype=np.float32)
class Model:
 def __init__(self,control,actual=None):self.control,self.actual,self.calls=control,actual,[]
 def pair_fits(self,q,text):
  self.calls.append(dict(op='pair_fits',query=q,text=text))
  if self.control.get('fail_pair'):raise ValueError('pair failed')
  return self.actual.pair_fits(q,text)if self.actual is not None else len(q)+len(text)<=self.control['pair_budget']
 def score(self,q,texts):
  self.calls.append(dict(op='score',query=q,texts=list(texts)))
  if self.control.get('fail_score'):raise ValueError('score failed')
  if self.actual is not None:return self.actual.score(q,texts)
  return [0. if self.control['mode']=='zero'else float(len(t)%19-9)/4 for t in texts],dict(model='controlled-piece-search',documents=len(texts))
assets=prepare_reranker(request['definition'],pathlib.Path(request['prepared']),source_snapshot=pathlib.Path(request['source']))
records=[]
for case in request['cases']:
 directory=pathlib.Path(request['catalog_root'])/case['id'];catalog=make_catalog(directory,case['files'])
 keys=[next(k for k in catalog.owners if(k.path,k.qualname)==tuple(selector))for selector in case['selectors']]
 physical=dict(files={p:list(s.encode())for p,s in case['files'].items()},owners=[dict(key=dataclasses.asdict(k),passages=[dataclasses.asdict(p)for p in passages])for k,passages in catalog.owners.items()])
 data=dict(physical=physical,keys=[dataclasses.asdict(k)for k in keys],**{k:case[k]for k in('scores','signals','request','expanded_query','exact','forest','disk','model')})
 matches=[CodeMatch(k,score,list(catalog.owners[k]),catalog.owners[k][0].source_hash,signal)for k,score,signal in zip(keys,case['scores'],case['signals'],strict=True)]
 tree={'value':0.}if case['forest']=='zero'else{'feature':0,'threshold':5.,'left':{'value':2.},'right':{'value':-1.}}
 ranker=PieceReranker(NumericRanker.from_dict(dict(schema=1,features=PIECE_FEATURES,trees=[tree])),Words(),stem_words=lambda words:list(words))
 actual=ONNXReranker(lambda:assets,**case['model'].get('options',{}))if case['model']['kind']=='ettin'else None
 neural=Model(case['model'],actual);search=original.PieceSearch(catalog,ranker,neural);observations=[]
 if case['disk']=='changed':(directory/next(iter(case['files']))).write_text('changed after snapshot construction\n')
 for attempt in range(2):
  neural.calls=[];row={}
  try:row['result']=search.search(SearchRequest(**case['request']),matches,expanded_query=case['expanded_query'],profile_version='piece-search-composition',exact=case['exact']).to_dict()
  except Exception as error:row['error']=dict(type=type(error).__name__,message=str(error))
  row.update(calls=neural.calls,cache=[dataclasses.asdict(d)for d in search.descriptions.values()]);observations.append(row)
 records.append(dict(id=case['id'],input=data,observations=observations))
 with (pathlib.Path(request['result']).parent/'records.jsonl').open('a')as stream:stream.write(json.dumps(records[-1],ensure_ascii=True)+'\n')
artifacts={name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())for name,p in [('model.onnx',assets.graph),('tokenizer.json',assets.tokenizer),('config.json',assets.config),('tokenizer_config.json',assets.tokenizer_config)]}
value=dict(definition=request['definition'],artifacts=artifacts,format='ken-piece-search-reference/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),packages={p:importlib.metadata.version(p)for p in('numpy','onnxruntime','onnx','tokenizers')}),original_source_sha256=hashlib.sha256(pathlib.Path(original.__file__).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def digest(value):return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-piece-search-reference/1','format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'observer differs')
        require(value['reference_fingerprint']==FP and value['original_source_sha256']==API_SHA,'original source differs')
        require(value['runtime']==dict(system='Linux',machine='x86_64',python='3.12.9',packages=dict(numpy='2.4.4',onnxruntime='1.25.1',onnx='1.20.1',tokenizers='0.22.2')),'runtime differs')
        definition=load(Path(__file__).resolve().parents[2]/'crates/ken-models/resources/ettin-68m-fp32.json')
        require(value['definition']==definition,'model registration differs')
        artifacts={'model.onnx':{k:definition['graph'][k]for k in('bytes','sha256')}}
        artifacts.update({n:definition['source']['artifacts'][n]for n in('tokenizer.json','config.json','tokenizer_config.json')})
        require(value['artifacts']==artifacts,'prepared model differs')
        require(value['inputs_sha256']==hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest(),'input definitions differ')
        require([r['id']for r in value['cases']]==[c['id']for c in cases()],'cases differ')
        for row,case in zip(value['cases'],cases(),strict=True):
            data=row['input'];require(set(data)=={'physical','keys','request','expanded_query','scores','signals','exact','forest','disk','model'},'foreign inputs')
            require(set(data['physical'])=={'files','owners'} and data['physical']['files']=={p:list(s.encode())for p,s in case['files'].items()},'physical bytes differ')
            for key in ('request','expanded_query','scores','signals','exact','forest','disk','model'):require(data[key]==case[key],key+' differs')
            owners=[o['key']for o in data['physical']['owners']]
            require(data['keys']==[next(k for k in owners if[k['path'],k['qualname']]==selector)for selector in case['selectors']],'selected keys differ')
            cold,warm=row['observations'];require(cold['calls']==warm['calls'] and cold['cache']==warm['cache'],'cache/call behavior differs')
            if case['model']['kind']=='controlled':require(cold==warm,'controlled observations differ')
            if not case['exact']:require(bool(cold['calls']),'missing model observation')
            else:require(not cold['calls'],'exact mode inferred')
        require(value['observations_sha256']==digest(value),'observations differ');return[]
    except(KeyError,TypeError,ValueError,StopIteration)as error:return[str(error)]
def capture(reference:Reference,out:Path):
    if out.exists():raise FileExistsError(out)
    authenticate_frozen(reference);out.mkdir(parents=True);(out/'capture.py').write_text(SCRIPT)
    definition=load(Path(__file__).resolve().parents[2]/'crates/ken-models/resources/ettin-68m-fp32.json')
    request=dict(reference=str(reference.root),cases=cases(),catalog_root=str(out/'catalogs'),result=str(out/'observations.json'),definition=definition,source=str(Path('.ken/rust-migration/x86-ettin/source')/definition['source']['revision']),prepared=str(out/'prepared'))
    request['source']=str(Path(request['source']).absolute());(out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    child=subprocess.run([str(Path(sys.executable).absolute()),'-B',str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=600)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError(child.stderr.decode(errors='replace'))
    authenticate_frozen(reference);value=load(out/'observations.json');value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=FP,inputs_sha256=hashlib.sha256(json.dumps(cases(),sort_keys=True).encode()).hexdigest());value['observations_sha256']=digest(value)
    require_errors=validate_reference(value)
    if require_errors:raise ValueError(require_errors)
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True)+'\n');return value
