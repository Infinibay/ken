"""First, disjoint observations of the frozen symbol neural-view policy."""
from pathlib import Path
import gzip,hashlib,json,subprocess
from .reference import Reference,reference_env,verify_reference
from .native_json import identity,load
from .ettin_reference import source_state

ROOT=Path(__file__).resolve().parents[2]
FIXTURE='crates/ken-retrieval/tests/fixtures/symbol-views-reference.json.gz'
SUITE=['tests/retrieval/test_symbol_ranking.py::test_explicit_purpose_prevents_test_granularity_from_overriding_the_caller','tests/retrieval/test_symbol_ranking.py::test_complete_pair_capacity_check_does_not_truncate_or_change_later_scoring']

def description(body='return value',signature='def sample():',path='a.py',name='sample'):
    return dict(entity=dict(path=path,kind='function',qualname=name,owner=None,definition_ordinal=0),source_hash='a'*64,fields=dict(executable=body,signature=signature),owned_lines=1,implementation_lines=1,executable_lines=1,comment_lines=0,regions=1,passages=[])

def cases():
    rows=[]
    def project(name,desc):rows.append(dict(id='projection-'+name,kind='projection',input=dict(descriptions=[desc])))
    for name,body in [('empty',''),('basic','return value'),('trailing','return value\n'),('nul','return\x00value'),('surrogate','return \ud800'),('astral','return 🙂'),('lines64','\n'.join(['x']*64)),('lines65','\n'.join(['x']*65)),('breaks64','\n'*64),('breaks65','\n'*65)]:project(name,description(body))
    project('none-name',description(name=None));project('empty-name',description(name=''))
    project('multiline-signature',description(signature='\n'.join(['signature']*100)))
    for length in(12000,12001):
        base=len('symbol a.py sample\ndef sample():\nImplementation:\n')
        project('chars'+str(length),description('a'*(length-base)))
        project('astral-chars'+str(length),description('🙂'*(length-base)))
    for i,separator in enumerate(['\n','\r','\r\n','\v','\f','\x1c','\x1d','\x1e','\x85','\u2028','\u2029']):
        for count in(64,65):project(f'linebreak{i}-{count}',description(separator.join(['x']*count)))
    for field in('executable','signature'):
        desc=description();del desc['fields'][field];project('missing-'+field,desc)
    def rank(name,descs,original,code,accepted=None,**kw):rows.append(dict(id='rank-'+name,kind='rank',input=dict(query='x',descriptions=descs,original_scores=original,code_scores=code,accepted=accepted or [],details={'model':'observed-fixture','pair_tokens':[7]},**kw)))
    a=description();b=description('return other',path='b.py',name='other');large=description('\n'.join(['large']*65),path='large.py')
    rank('empty',[],[],[]);rank('single',[a],[1.],[3.]);rank('negative',[a,b],[-4.,-2.],[-2.,-5.]);rank('ties',[a,b],[0.,2.],[2.,0.])
    rank('duplicates',[a,b,a],[1.,2.,3.],[8.,-2.]);rank('duplicate-mixed-admission',[a,a,a],[1.,2.,3.],[8.],[True,False,True])
    rank('oversize-fallback',[a,large,b],[1.,6.,2.],[4.,0.]);rank('capacity-fallback',[a,b],[4.,2.],[8.],[False,True])
    rank('all-fallback',[a,b],[4.,2.],[],[False,False]);rank('no-pairs-over-limit',[large],[7.],[])
    rank('overflow-grouping',[a,b],[1.1e308,1.],[1.1e308,1.]);rank('fallback-overflow',[large],[1.1e308],[])
    rank('signed-zero',[a,b],[-0.,0.],[-0.,0.]);rank('top10',[description(path=f'{i}.py')for i in range(10)],[0.]*10,[float(i)for i in range(10)])
    rank('bad-original-count',[a,b],[0.],[1.],fail_pair=0);rank('top11',[description(path=f'{i}.py')for i in range(11)],[0.]*11,[],fail_pair=0)
    rank('bad-model-short',[a],[0.],[]);rank('bad-model-long',[a],[0.],[1.,2.]);rank('pair-failure',[a],[0.],[1.],fail_pair=0);rank('score-failure',[a],[0.],[1.],fail_score=True)
    return rows

def frames():
    a=description();large=description('\n'.join(['large']*65),path='large.py')
    return[
        dict(id='real-single',query='x',descriptions=[a],card_texts=['symbol a.py sample\nreturn value'],options={}),
        dict(id='real-duplicates-fallback',query='x',descriptions=[a,a,large],card_texts=['first card','second card','large card'],options={}),
        dict(id='real-capacity',query='x',descriptions=[description('alpha '*400)],card_texts=['small card'],options={'max_tokens':128}),
        dict(id='real-top10',query='x',descriptions=[description(path=f'{i}.py',body='return value '+str(i))for i in range(10)],card_texts=['card '+str(i)for i in range(10)],options={}),
        dict(id='real-all-oversized',query='x',descriptions=[large],card_texts=['large card'],options={}),
    ]

SCRIPT=r'''
import dataclasses,hashlib,importlib.metadata,json,math,pathlib,platform,sys
import pytest
from types import SimpleNamespace
import ken.retrieval.symbol_ranking as original
from ken.retrieval.description import OwnerDescription
from ken.retrieval.model import EntityKey,SearchRequest
from ken.retrieval.symbol_requirements import requirements
from ken.retrieval.reranker_fusion import fused_reranker_order
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.neural_assets import prepare_reranker
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['reference'])
assert pathlib.Path(original.__file__).resolve().is_relative_to(root/'src')
def desc(value):return OwnerDescription(**{**value,'entity':EntityKey(**value['entity']),'passages':()})
def clean(value):
 if isinstance(value,float)and not math.isfinite(value):return{'$float':'nan'if math.isnan(value)else'inf'if value>0 else'-inf'}
 if isinstance(value,dict):return{k:clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return[clean(v)for v in value]
 return value
class Observed:
 def __init__(self,data,actual=None):self.data,self.actual,self.calls,self.index=data,actual,[],0
 def pair_fits(self,q,text):
  self.calls.append(dict(op='pair_fits',query=q,text=text));i=self.index;self.index+=1
  if self.data.get('fail_pair')==i:raise ValueError('pair failed')
  if self.actual is not None:return self.actual.pair_fits(q,text)
  values=self.data.get('accepted',[]);return values[i]if i<len(values)else True
 def score(self,q,texts):
  self.calls.append(dict(op='score',query=q,texts=list(texts)))
  if self.data.get('fail_score'):raise ValueError('score failed')
  if self.actual is not None:return self.actual.score(q,texts)
  return self.data['code_scores'],self.data['details']
def rank(data,neural,scores):
 descriptions=[desc(d)for d in data['descriptions']];keys=[d.entity for d in descriptions]
 request_=SearchRequest(data['query'],purpose='implementation');required=requirements(request_)
 assert not required.operations and not required.operators and not required.test_case
 catalog=SimpleNamespace(owners={});cache={d.entity:d for d in descriptions}
 cards=[{'unit':{'path':k.path,'entity':{name:value for name,value in dataclasses.asdict(k).items()if name!='path'}}}for k in keys]
 result=original.SymbolRanker(catalog,neural,cache).rank(request_,cards,data['query'],scores)
 return dict(views=[original.complete_code_view(d)for d in descriptions],order=result.order,code_scores=result.code_scores,mean_scores=result.mean_scores,code_view_used=result.code_view_used,additional_inference=result.additional_inference)
records=[]
for case in request['cases']:
 data=case['input'];neural=Observed(data)
 try:
  result={'view':original.complete_code_view(desc(data['descriptions'][0]))}if case['kind']=='projection'else rank(data,neural,data['original_scores'])
  records.append(dict(**case,result=clean(result),calls=neural.calls))
 except Exception as e:records.append(dict(**case,error={'type':type(e).__name__,'message':str(e)},calls=neural.calls))
assets=prepare_reranker(request['definition'],pathlib.Path(request['prepared']),source_snapshot=pathlib.Path(request['source']))
artifacts={name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}for name,p in [('model.onnx',assets.graph),('tokenizer.json',assets.tokenizer),('config.json',assets.config),('tokenizer_config.json',assets.tokenizer_config)]}
real=[]
for data in request['frames']:
 actual=ONNXReranker(lambda:assets,**data['options']);neural=Observed({},actual)
 scores,details=neural.score(data['query'],data['card_texts']);result=rank(data,neural,scores)
 real.append(dict(input=data,result=clean(dict(original_scores=scores,first_inference=details,**result)),calls=neural.calls))
extension=dict(input=dict(scores=[0.,1.],weight=.5,offset=float(2**53)),result=fused_reranker_order([0.,1.],neural_weight=.5,rank_offset=float(2**53)))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-symbol-views-reference/1',cases=records,frames=real,fusion_grouping_extension=extension,artifacts=artifacts,discovered=discovered,test_states=states,original_test_exit=code,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),packages={p:importlib.metadata.version(p)for p in('numpy','onnxruntime','onnx','tokenizers')}))
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(code)
'''

def observations_digest(value):
    return hashlib.sha256(json.dumps({key:value[key]for key in('cases','frames','fusion_grouping_extension','artifacts')},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def validate_reference(value):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-symbol-views-reference/1','symbol view reference format differs')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'symbol view observer differs')
        require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==cases(),'symbol view inputs differ')
        require([f['input']for f in value['frames']]==frames(),'real symbol view frames differ')
        require(all(('result'in c)^('error'in c)for c in value['cases']),'incomplete symbol view observations')
        require(len({c['id']for c in value['cases']})==len(value['cases'])and value['observations_sha256']==observations_digest(value),'symbol view observations differ')
        require(value['original_test_exit']==0 and len(value['discovered'])==len(set(value['discovered']))==2,'symbol view original test roots differ')
        require({s['nodeid']for s in value['test_states']}==set(value['discovered'])and all(s['when']=='call'and s['outcome']=='passed'for s in value['test_states']),'symbol view original tests incomplete')
        require(value['runtime']['system']=='Linux'and value['runtime']['machine']=='x86_64'and value['runtime']['python']=='3.12.9','symbol view original host differs')
        require(value['runtime']['packages']==dict(numpy='2.4.4',onnxruntime='1.25.1',onnx='1.20.1',tokenizers='0.22.2'),'symbol view original dependencies differ')
        require(value['reference_fingerprint']=='5b849bf6f01a5915aea972274dba5bd00073bf42efab6563297c2ded0e368038','symbol view frozen source differs')
        definition=load(ROOT/'crates/ken-models/resources/ettin-68m-fp32.json')
        require(value['source_artifacts']==definition['source']['artifacts'],'symbol view model source differs')
        artifacts={'model.onnx':{k:definition['graph'][k]for k in('bytes','sha256')}}
        artifacts.update({name:definition['source']['artifacts'][name]for name in('tokenizer.json','config.json','tokenizer_config.json')})
        require(value['artifacts']==artifacts,'symbol view prepared graph differs')
        return[]
    except(KeyError,TypeError,ValueError)as e:return[str(e)]

def capture(reference:Reference,out:Path,source:Path):
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen source drift')
    out.mkdir(parents=True,exist_ok=False)
    definition=load(reference.root/'src/ken/embedder/data/ettin-68m-fp32.json');state=source_state(source,definition['source'])
    (out/'capture.py').write_text(SCRIPT)
    request=dict(reference=str(reference.root),cases=cases(),frames=frames(),definition=definition,source=str(source),prepared=str(out/'original-prepared'),suite=SUITE,junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
    (out/'inputs.json').write_text(json.dumps(request,ensure_ascii=True)+'\n')
    child=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'inputs.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=600)
    (out/'stdout.log').write_bytes(child.stdout);(out/'stderr.log').write_bytes(child.stderr)
    if child.returncode:raise ValueError('frozen symbol view capture failed: '+child.stdout.decode(errors='replace')[-2000:]+child.stderr.decode(errors='replace')[-1000:])
    value=load(out/'observations.json');value.update(script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),reference_fingerprint=reference.fingerprint,source_artifacts=state)
    value['observations_sha256']=observations_digest(value)
    if verify_reference(reference.root,reference.manifest_path)or source_state(source,definition['source'])!=state:raise ValueError('symbol view original/source changed')
    errors=validate_reference(value)
    if errors:raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n')
    return value
