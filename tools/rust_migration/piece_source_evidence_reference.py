"""Original source-bounded completion, judge windows and lexical cue selection."""
SCRIPT = r'''
import dataclasses,importlib,json,math,pathlib,platform,sys,tempfile,unicodedata
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Passage,Span,CodeMatch,SearchRequest
from ken.retrieval import evidence,source_evidence
for module in (evidence,source_evidence):
 if not pathlib.Path(module.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original source evidence')
def passage(v):return Passage(**{**v,'entity':EntityKey(**v['entity']),'span':Span(**v['span']),'entity_span':Span(**v['entity_span'])})
def match(v):return CodeMatch(EntityKey(**v['entity']),v['score'],[passage(p)for p in v['evidence']],v['source_hash'],v.get('signals',{}),tuple(Span(**s)for s in v.get('owned_regions',[])))
def clean(v):
 if dataclasses.is_dataclass(v):return clean(dataclasses.asdict(v))
 if isinstance(v,np.ndarray):return clean(v.tolist())
 if isinstance(v,np.generic):return clean(v.item())
 if isinstance(v,float)and not math.isfinite(v):return{'$float':'nan'if math.isnan(v)else'inf'if v>0 else'-inf'}
 if isinstance(v,dict):return{k:clean(x)for k,x in v.items()}
 if isinstance(v,(list,tuple)):return[clean(x)for x in v]
 return v
records=[]
for case in request['cases']:
 data=case['input'];calls=[]
 with tempfile.TemporaryDirectory(prefix='ken-original-evidence-')as temporary:
  base=pathlib.Path(temporary);project=base/'project';project.mkdir()
  for name,content in data['files'].items():
   p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes(content))
  try:
   matches=[match(v)for v in data['matches']];before=clean(matches);search=SearchRequest(**data['request'])
   class Judge:
    def score(self,query,documents,*,purpose):
     calls.append(dict(operation='judge',query=query,documents=documents,purpose=purpose));mode=data['judge']['mode']
     if mode=='contains':return[3. if all(word in doc for word in data['judge']['needles'])else -1. for doc in documents]
     if mode=='ties':return[0.]*len(documents)
     if mode=='negative':return[-float(i+1)for i in range(len(documents))]
     if mode=='wrong-size':return[0.]*(len(documents)+1)
     if mode in('nan','inf'):return[float(mode)]*len(documents)
     raise ValueError('unknown scripted judge')
   def stem(words):
    calls.append(dict(operation='stem',words=words.copy()));return[data['stems'].get(w,w)for w in words]
   mutation=data.get('mutation')
   if mutation:
    target=project/mutation['path']
    if mutation['op']=='write':target.write_bytes(bytes(mutation['bytes']))
    elif mutation['op']=='symlink':
     outside=base/'outside.py';outside.write_text('outside fixture\n');target.unlink();target.symlink_to(outside)
    elif mutation['op']=='replace-root':
     project.rename(base/'old-project');project.mkdir();target=project/mutation['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes(mutation['bytes']))
    else:raise ValueError('unknown source mutation')
   operation=data['operation'];owner=matches[0]
   if operation=='verified':value=evidence.verified_lines(project,owner)
   elif operation=='extent':value=evidence.entity_extent(owner)
   elif operation=='bounds':value=evidence.source_bounds(owner,owner.evidence[0],len(bytes(data['files'][owner.entity.path]).decode('utf-8').splitlines()),implementation=data.get('implementation',True))
   elif operation=='complete-owner':value=evidence.complete_owned_context(owner,project)
   elif operation=='complete':value=evidence.complete_evidence(matches,project,search)
   elif operation=='refine':value=evidence.refine_evidence(matches,project,search,judge=Judge(),**data['options'])
   elif operation=='lexical':value=source_evidence.refine_source_evidence(matches,project,search,query=data['expanded_query'],stem_words=stem)
   else:raise ValueError('unknown evidence operation')
   records.append(dict(**case,result=clean(dict(value=value,calls=calls,unchanged=before==clean(matches)))))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error).replace(str(project),'{project}').replace(str(base),'{scenario}')),calls=clean(calls)))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-piece-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
