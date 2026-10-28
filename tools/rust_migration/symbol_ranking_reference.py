"""Independent complete SymbolRanker observations, without original pytest runs."""
from pathlib import Path
import gzip,hashlib,json,subprocess,sys
from .reference import Reference,reference_env
from .execution_profiles import authenticate_frozen,FP
from .native_json import load
FIXTURE='crates/ken-retrieval/tests/fixtures/symbol-ranking-reference.json.gz'
API_SHA='4df8c293968543cfc5c5c1b54d9931f7faa4945744ece34d3897858f89471a2d'
def cases():
    source='''def wrapper(error):
    return str(error)
def annotate(error):
    raise AttributeError("location") from error
def snapshot(mapping,key,new,log):
    old = mapping.get(key, None)
    mapping[key] = new
    log.append((mapping,key,old))
def refresh(flag):
    return flag or (flag := action())
def value_only(value):
    return value
def deferred():
    def later():
        return action()
    return later
def logic(a,b):
    return a and b
def either(a,b):
    return a or b
def test_checks(a,b):
    assert a and b
'''
    rows=[]
    def add(name,query='Find a value',names=('wrapper','annotate'),scores=None,*,files=None,path='sample.py',expanded=None,purpose='auto',model=None):
        rows.append(dict(id=name,files=files or {path:source},selectors=[[path,n]for n in names],request=dict(query=query,purpose=purpose),expanded_query=expanded if expanded is not None else query,original_scores=scores if scores is not None else [float(i)for i in range(len(names))],model=model or dict(kind='controlled',mode='length',pair_budget=10000)))
    queries=[('plain','Find a value'),('cause','Find the attribute error that retains the original exception as its cause.'),('any-cause','Preserve the exception cause'),('invocation','Find code that invokes an action'),('no-invocation','Find code without invoking an action'),('snapshot','Write a mapping key remembering the previous value'),('refresh','Return a flag or refresh the state'),('operator','Find AND and OR expressions'),('quoted','Find `not` expressions'),('bitwise','Find bitwise OR for flags'),('tests','Which regression checks the value?')]
    for name,q in queries:add('query-'+name,q,names=('wrapper','annotate','snapshot','refresh','value_only','deferred','logic','either','test_checks'),scores=[90.,0.,0.,0.,20.,30.,0.,0.,0.])
    for mode in ('zero','length'):
        add('ties-'+mode,names=('logic','either','value_only'),scores=[0.,0.,0.],model=dict(kind='controlled',mode=mode,pair_budget=10000))
        add('duplicates-'+mode,names=('annotate','wrapper','annotate'),scores=[1.,20.,3.],model=dict(kind='controlled',mode=mode,pair_budget=10000))
    add('request-original-operations','Find code that invokes an action',names=('value_only','wrapper'),scores=[100.,0.],expanded='Find value')
    add('expanded-not-requirement','Find value',names=('value_only','wrapper'),scores=[100.,0.],expanded='Find code that invokes an action')
    add('request-original-operator','Find AND expressions',names=('either','logic'),scores=[100.,0.],expanded='Find OR expressions')
    for purpose in ('auto','implementation','tests'):
        add('purpose-'+purpose,'Which regression checks AND expressions?',names=('logic','test_checks','either'),scores=[100.,0.,200.],purpose=purpose,path='test_composition.py')
    add('all-priorities','Which regression test invokes an action using AND expressions?',names=('wrapper','logic','test_checks'),scores=[200.,100.,0.],path='test_composition.py')
    add('no-required-witnesses','Find a value',names=('annotate','snapshot','refresh'),scores=[0.,0.,0.])
    add('empty',names=(),scores=[])
    add('bad-count',scores=[1.])
    many=''.join(f'def f{i}():\n    return {i}\n'for i in range(11))
    add('top10',names=tuple(f'f{i}'for i in range(10)),files={'sample.py':many})
    add('top11',names=tuple(f'f{i}'for i in range(11)),files={'sample.py':many})
    add('capacity-fallback',model=dict(kind='controlled',mode='length',pair_budget=1))
    big='def large():\n'+''.join(f'    value_{i}={i}\n'for i in range(70))
    add('oversize-fallback',names=('large','wrapper'),files={'sample.py':big+source})
    add('pair-error',model=dict(kind='controlled',mode='length',pair_budget=10000,fail_pair=True))
    add('score-error',model=dict(kind='controlled',mode='length',pair_budget=10000,fail_score=True))
    for path,body in [('sample.js','function wrapper(){ return value; }\nfunction annotate(){ throw new Error("x", {cause:error}); }\n'),('Sample.java','class Sample {\n    int wrapper(){\n        return 1;\n    }\n    void annotate(){\n        throw new IllegalStateException("x", error);\n    }\n}\n')]:
        names=('wrapper','annotate')if path.endswith('.js')else('Sample.wrapper','Sample.annotate')
        add('router-'+path.split('.')[-1],'Preserve the exception cause',path=path,names=names,files={path:body},scores=[100.,0.])
    for name,q,names,options in [('cause','Find the attribute error that retains the original exception as its cause.',('wrapper','annotate'),{}),('test-operator','Which regression checks AND expressions?',('logic','test_checks','either'),{}),('fallback','Find value',('large','wrapper'),{'max_tokens':128})]:
        add('real-'+name,q,names=names,path='test_composition.py',files={'test_composition.py':big+source},model=dict(kind='ettin',options=options))
    return rows
SCRIPT=r'''
import dataclasses,hashlib,importlib.metadata,json,math,pathlib,platform,sys
import ken.retrieval.symbol_ranking as original
from ken.retrieval.model import SearchRequest
from ken.retrieval.piece_cards import build_card,card_text
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.neural_assets import prepare_reranker
from tests.retrieval.test_symbol_ranking import make_catalog
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
def clean(value):
 if isinstance(value,float)and not math.isfinite(value):return{'$float':'nan'if math.isnan(value)else'inf'if value>0 else'-inf'}
 if isinstance(value,dict):return{k:clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple,set,frozenset)):return[clean(v)for v in(sorted(value)if isinstance(value,(set,frozenset))else value)]
 return value
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
  return [0. if self.control['mode']=='zero'else float(len(t)%19-9)/4 for t in texts],dict(model='controlled-symbol-composition',documents=len(texts))
assets=prepare_reranker(request['definition'],pathlib.Path(request['prepared']),source_snapshot=pathlib.Path(request['source']))
records=[]
for case in request['cases']:
 directory=pathlib.Path(request['catalog_root'])/case['id'];catalog=make_catalog(directory,case['files'])
 keys=[next(k for k in catalog.owners if(k.path,k.qualname)==tuple(selector))for selector in case['selectors']]
 req=SearchRequest(**case['request']);q=case['expanded_query'];cards=[build_card(k,'symbol',[k],q,catalog)for k in keys]
 physical=dict(files={p:list(s.encode())for p,s in case['files'].items()},owners=[dict(key=dataclasses.asdict(k),passages=[dataclasses.asdict(p)for p in passages])for k,passages in catalog.owners.items()])
 data=dict(physical=physical,keys=[dataclasses.asdict(k)for k in keys],request=case['request'],expanded_query=q,original_scores=case['original_scores'],model=case['model'])
 cache={};actual=ONNXReranker(lambda:assets,**case['model'].get('options',{}))if case['model']['kind']=='ettin'else None
 neural=Model(case['model'],actual);ranker=original.SymbolRanker(catalog,neural,cache);observations=[]
 for path in case['files']:(directory/path).write_text('changed after snapshot construction\n')
 for attempt in range(2):
  neural.calls=[];row={}
  try:
   scores=case['original_scores']
   if actual is not None:
    scores,details=neural.score(q,[card_text(c)for c in cards]);row.update(first_scores=scores,first_inference=details)
   result=ranker.rank(req,cards,q,scores);row['result']=clean(dataclasses.asdict(result))
  except Exception as error:row['error']=dict(type=type(error).__name__,message=str(error))
  row.update(calls=neural.calls,cache=[dataclasses.asdict(d)for d in cache.values()]);observations.append(clean(row))
 records.append(dict(id=case['id'],input=data,observations=observations))
 with (pathlib.Path(request['result']).parent/'records.jsonl').open('a')as stream:stream.write(json.dumps(records[-1],ensure_ascii=True)+'\n')
artifacts={name:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())for name,p in [('model.onnx',assets.graph),('tokenizer.json',assets.tokenizer),('config.json',assets.config),('tokenizer_config.json',assets.tokenizer_config)]}
value=dict(definition=request['definition'],artifacts=artifacts,format='ken-symbol-ranking-reference/1',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),packages={p:importlib.metadata.version(p)for p in('numpy','onnxruntime','onnx','tokenizers')}),original_source_sha256=hashlib.sha256(pathlib.Path(original.__file__).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def digest(value):return hashlib.sha256(json.dumps(value['cases'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-symbol-ranking-reference/1','format differs')
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
            data=row['input'];require(set(data)=={'physical','keys','request','expanded_query','original_scores','model'},'foreign inputs')
            require(set(data['physical'])=={'files','owners'} and data['physical']['files']=={p:list(s.encode())for p,s in case['files'].items()},'physical bytes differ')
            for key in ('request','expanded_query','original_scores','model'):require(data[key]==case[key],key+' differs')
            owners=[o['key']for o in data['physical']['owners']]
            require(data['keys']==[next(k for k in owners if[k['path'],k['qualname']]==selector)for selector in case['selectors']],'selected keys differ')
            cold,warm=row['observations'];require(cold['calls']==warm['calls'] and cold['cache']==warm['cache'],'cache/call behavior differs')
            if case['model']['kind']=='controlled':require(cold==warm,'controlled observations differ')
            if len(data['keys'])==len(data['original_scores'])and len(data['keys'])<=10:require(bool(cold['calls']),'missing model observation')
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
