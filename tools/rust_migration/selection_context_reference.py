"""Original contextual source ownership and registered source-view observations."""
SCRIPT=r'''
import dataclasses,importlib,json,pathlib,platform,sys,unicodedata
from collections import OrderedDict
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Span,Passage,Candidate
from ken.retrieval.profile import EncoderSpec,ContextualRetrieval
from ken.retrieval.contextual import OwnerVectorSnapshot,ContextualRetriever
from ken.retrieval.source_views import SourceViewSnapshot,owner_view_texts
from ken.retrieval.description import describe_owner
for name in ['contextual','source_views','description']:
 if not pathlib.Path(importlib.import_module('ken.retrieval.'+name).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original contextual module')
def p(value):
 value=dict(value);value['entity']=EntityKey(**value['entity']);value['span']=Span(**value['span']);value['entity_span']=Span(**value['entity_span']);return Passage(**value)
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
 if isinstance(value,dict):return {str(k):clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [clean(v)for v in value]
 if isinstance(value,np.ndarray):return clean(value.tolist())
 if isinstance(value,np.generic):return value.item()
 return value
records=[]
for case in request['cases']:
 data=case['input'];calls=[]
 try:
  if case['kind']=='view_texts':result=owner_view_texts(describe_owner([p(v)for v in data['passages']]))
  else:
   owners=OrderedDict((EntityKey(**e),[p(v)for v in ps])for e,ps in data['owners'])
   keys=tuple(EntityKey(**e)for e in data.get('owner_keys',list(e for e,ps in data['owners'])))
   hashes=tuple(data.get('source_hashes',[ps[0].source_hash for ps in owners.values()]))
   model=EncoderSpec(**data['model']);source_views=None
   if data.get('views')is not None:
    v=data['views'];source_views=SourceViewSnapshot(EncoderSpec(**v['model']),v.get('generation',data['snapshot_generation']),tuple(EntityKey(**e)for e in v.get('owners',[e for e,ps in data['owners']])),tuple(v.get('source_hashes',hashes)),np.asarray(v['matrix'],dtype=np.float32),{name:np.asarray(rows)for name,rows in v['rows'].items()},query_model=EncoderSpec(**v.get('query_model',data['model'])))
   selected=[Candidate(e,list(owners[e]))for e in list(owners)[::1]if e in owners]
   selected=[selected[i]for i in data.get('enrich_indices',[2,0])]
   if case['kind']=='source_views':
    original=np.asarray(data['query_vectors'][data['original']],dtype=np.float32);expanded=original if data['original']==data['expanded']else np.asarray(data['query_vectors'][data['expanded']],dtype=np.float32)
    source_views.enrich(selected,original,expanded);result=dict(candidates=selected,query_calls=calls)
   else:
    vectors=OwnerVectorSnapshot(model,data['snapshot_generation'],keys,hashes,np.asarray(data['matrix'],dtype=np.float32),data.get('projection_version',1))
    class Encoder:
     spec=EncoderSpec(**data.get('encoder_model',data['model']))
     def embed_query(self,text):calls.append(text);return np.asarray(data['query_vectors'][text],dtype=np.float32)
    engine=ContextualRetriever(Encoder(),vectors,source_views=source_views)
    policy=ContextualRetrieval(EncoderSpec(**data.get('policy_model',data['model'])),channel_limit=2,broad_limit=8,view_model=EncoderSpec(**data['policy_view_model'])if data.get('policy_view_model')is not None else None)
    current=owners
    if data.get('omit_owner'):current=OrderedDict(list(owners.items())[:-1])
    if data.get('stale_owner'):
     current=OrderedDict(owners);e=next(iter(current));current[e]=[dataclasses.replace(v,source_hash='changed')for v in current[e]]
    scores=engine.score(data['original'],data['expanded'],current,generation=data['generation'],policy=policy)
    proposed=scores.propose(current,limit=data.get('limit',2));scores.enrich(selected)
    result=dict(original=scores.original,expanded=scores.expanded,proposed=proposed,candidates=selected,query_calls=calls)
  records.append(dict(**case,result=clean(result)))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),query_calls=calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-selection-reference/1',family='context',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
