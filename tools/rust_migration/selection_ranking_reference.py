"""Actual original entity/passage ranking and the documents delivered to its judge."""
SCRIPT=r'''
import dataclasses,importlib,json,pathlib,platform,sys,unicodedata
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Span,Passage,Candidate,SearchRequest
from ken.retrieval.ranking import candidate_document,rank_candidates
if not pathlib.Path(importlib.import_module('ken.retrieval.ranking').__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original ranking module')
def p(value):
 value=dict(value);value['entity']=EntityKey(**value['entity']);value['span']=Span(**value['span']);value['entity_span']=Span(**value['entity_span']);return Passage(**value)
def c(value):return Candidate(EntityKey(**value['entity']),[p(v)for v in value['passages']],value['signals'],[Span(**s)for s in value['owned_regions']])
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
 if isinstance(value,dict):return {str(k):clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [clean(v)for v in value]
 if isinstance(value,np.generic):return value.item()
 return value
records=[]
for case in request['cases']:
 data=case['input'];calls=[]
 class Judge:
  def score(self,query,documents,*,purpose):
   calls.append(dict(query=query,documents=documents,purpose=purpose))
   return np.asarray(data['scores'],dtype=np.float64)if 'scores'in data else np.asarray([3. if 'remove_credentials'in doc else -2. for doc in documents])
 try:
  if case['kind']=='document':result=candidate_document(c(data['candidate']),purpose=data['purpose'])
  else:
   candidates=[c(v)for v in data['candidates']];before=clean(candidates)
   result=dict(matches=clean(rank_candidates(SearchRequest(**data['request']),candidates,judge=Judge()if data['judge']else None,rerank_limit=data['rerank_limit'],rank_unit=data['rank_unit'])),judge_calls=calls,unchanged=clean(candidates)==before)
  records.append(dict(**case,result=clean(result)))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error)),judge_calls=calls))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-selection-reference/1',family='ranking',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
