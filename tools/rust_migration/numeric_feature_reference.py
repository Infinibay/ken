"""Original complete owner features and explicit encoder/stemmer interactions."""
SCRIPT=r'''
import dataclasses,importlib,json,math,pathlib,platform,sys,unicodedata,warnings
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Span,Passage,Candidate,SearchRequest
from ken.retrieval.description import describe_owner
from ken.retrieval.evidence_features import base_features,_coverage,evidence_features,FEATURES
from ken.retrieval.contextual_features import contextual_features
from ken.retrieval.owner_ranking import EvidenceReranker
for name in ['evidence_features','contextual_features']:
 if not pathlib.Path(importlib.import_module('ken.retrieval.'+name).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original feature owner')
def restore(value):
 if isinstance(value,dict):
  if set(value)=={'$float'}:return float(value['$float'])
  return{k:restore(v)for k,v in value.items()}
 if isinstance(value,list):return[restore(v)for v in value]
 return value
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
 if isinstance(value,np.ndarray):return clean(value.tolist())
 if isinstance(value,np.generic):return clean(value.item())
 if isinstance(value,float)and not math.isfinite(value):return{'$float':'nan'if math.isnan(value)else'inf'if value>0 else'-inf'}
 if isinstance(value,dict):return{str(k):clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return[clean(v)for v in value]
 return value
def passage(v):return Passage(**{**v,'entity':EntityKey(**v['entity']),'span':Span(**v['span']),'entity_span':Span(**v['entity_span'])})
def candidate(v):return Candidate(EntityKey(**v['entity']),[passage(p)for p in v['passages']],v.get('signals',{}),[Span(**s)for s in v.get('owned_regions',[])])
def vector(text):
 if not text:return np.zeros(3,dtype=np.float32)
 value=sum(ord(c)for c in text)%6;v=np.zeros(3,dtype=np.float32);v[value%3]=1. if value<3 else -1.;return v
records=[]
for case in request['cases']:
 data=restore(case['input']);calls=[];stem_calls=[]
 class Encoder:
  def embed_query(self,text):calls.append(dict(op='query',text=text));return vector(text)
  def embed_passages(self,texts):
   calls.append(dict(op='passages',texts=list(texts)))
   if len(texts)>4096:raise ValueError('word vector block exceeds4096')
   return np.asarray([vector(t)for t in texts],dtype=np.float32)
 def stems(words):
  stem_calls.append(list(words));return EvidenceReranker.stem_words(words)if data.get('stemmer')=='english'else list(words)
 try:
  kind=case['kind']
  with warnings.catch_warnings():
   warnings.simplefilter('ignore',RuntimeWarning)
   if kind=='coverage':result=_coverage(data['query'],data['documents'],data['fields'],encoder=Encoder(),stem_words=stems if data.get('stemmer')else None)
   else:
    candidates=[candidate(v)for v in data['candidates']]
    if kind=='base':result=[base_features(SearchRequest(**data['request']),c)for c in candidates]
    elif kind=='feature_context':result=contextual_features(candidates,source_views=data['source_views'])
    else:
     descriptions={}
     for item in data['owners']:
      d=describe_owner([passage(p)for p in item['passages']])
      for k,v in item.get('overrides',{}).items():d=dataclasses.replace(d,**{k:EntityKey(**v)if k=='entity'else v})
      descriptions[EntityKey(**item['key'])]=d
     result=evidence_features(SearchRequest(**data['request']),candidates,descriptions,encoder=Encoder(),stem_words=stems,expanded_query=data.get('expanded'))
  records.append(dict(**case,result=clean(result),encoder_calls=calls,stemmer_calls=stem_calls))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),encoder_calls=calls,stemmer_calls=stem_calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),feature_names=FEATURES,discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
