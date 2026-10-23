"""Disjoint, immutable observations from the frozen numeric-owner original."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from .reference import Reference,reference_env
from .native_json import load,identity
from .selection_reference import owners
from .retrieval_reference import digest
ROOT=Path(__file__).resolve().parents[2]
SUITES={'forest':['tests/retrieval/test_numeric_ranker.py']}
SCRIPT=r'''
import importlib,json,math,pathlib,platform,sys,unicodedata,warnings
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.numeric_ranker import NumericRanker
if not pathlib.Path(importlib.import_module('ken.retrieval.numeric_ranker').__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original numeric module')
def restore(value):
 if isinstance(value,dict):
  if set(value)=={'$float'}:return float(value['$float'])
  return{k:restore(v)for k,v in value.items()}
 if isinstance(value,list):return[restore(v)for v in value]
 return value
def clean(value):
 if isinstance(value,np.ndarray):return clean(value.tolist())
 if isinstance(value,np.generic):return clean(value.item())
 if isinstance(value,float)and not math.isfinite(value):return{'$float':'nan'if math.isnan(value)else'inf'if value>0 else'-inf'}
 if isinstance(value,dict):return{k:clean(v)for k,v in value.items()}
 if isinstance(value,(list,tuple)):return[clean(v)for v in value]
 return value
records=[]
with warnings.catch_warnings():
 warnings.simplefilter('ignore',RuntimeWarning)
 for case in request['cases']:
  data=restore(case['input'])
  try:
   model=NumericRanker.from_dict(data['model']);kind=case['kind']
   if kind=='model':result=dict(model=model.to_dict(),canonical=json.dumps(model.to_dict(),sort_keys=True,separators=(',',':'),ensure_ascii=False),fingerprint=model.fingerprint)
   elif kind=='dict':result=model.to_dict()
   elif kind=='predict':
    matrix=np.asarray(data['values'],dtype=np.float64).reshape(data['rows'],data['columns']);before=model.to_dict();scores=model.predict(matrix)
    result=dict(scores=scores,unchanged=before==model.to_dict())
   elif kind=='explain':result=model.explain_pair(data['left'],data['right'])
   else:raise ValueError('unknown numeric operation')
   records.append(dict(**case,result=clean(result)))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error))))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
EDGES_SCRIPT=SCRIPT.replace("exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])","cached=json.loads(pathlib.Path(request['cached_suite']).read_bytes());discovered=cached['discovered'];states=cached['test_states'];exit_code=cached['original_test_exit']")
SCRIPTS={'forest':SCRIPT,'forest-edges':EDGES_SCRIPT}
def definitions(family:str,repo:Path=ROOT):return load(repo/f'crates/ken-retrieval/tests/fixtures/numeric-inputs-{family}.json')['cases']
def validate_reference(value:dict,family:str,repo:Path=ROOT):
 try:
  def require(ok,message):
   if not ok:raise ValueError(message)
  require(value['format']=='ken-numeric-reference/1'and value['family']==family,'original numeric family differs')
  require(value['script_sha256']==hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),'original numeric observer differs')
  require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==definitions(family,repo),'original numeric input inventory differs')
  require(all(('result'in c)^('error'in c)for c in value['cases'])and digest(value['cases'])==value['corpus_sha256'],'original numeric observations differ')
  require(value['execution']['exit']==0 and value['original_test_exit']==0,'original numeric process/suite failed')
  found=value['discovered'];states=value['test_states'];require(found and len(set(found))==len(found),'original numeric discovery absent/duplicated')
  require({s['nodeid']for s in states}==set(found)and all(s['when']=='call'and s['outcome']=='passed'for s in states),'original numeric suite incomplete')
  return[]
 except(KeyError,ValueError,TypeError)as error:return[str(error)]
def capture(reference:Reference,out:Path,repo:Path=ROOT,family:str='forest',cached_suite:Path|None=None):
 expected=owners(repo)
 for name,sha in expected.items():
  if identity(reference.root/name)['sha256']!=sha:raise ValueError('original numeric owner changed: '+name)
 if(out/'reference.json').exists():
  value=load(out/'reference.json');errors=validate_reference(value,family,repo)
  if errors or value['owners']!=expected:raise ValueError(errors or'original numeric owner inventory differs')
  return value
 out.mkdir(parents=True,exist_ok=False);(out/'capture.py').write_text(SCRIPTS[family])
 request=dict(root=str(reference.root),family=family,cases=definitions(family,repo),suite=SUITES.get(family,[]),junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
 if family=='forest-edges':
  if cached_suite is None:raise ValueError('original numeric suite predecessor required')
  cached_suite=cached_suite.resolve();previous=load(cached_suite)
  if validate_reference(previous,'forest',repo):raise ValueError('original numeric suite predecessor invalid')
  request['cached_suite']=str(cached_suite)
 (out/'request.json').write_text(json.dumps(request,ensure_ascii=True))
 proc=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
 (out/'stdout.log').write_bytes(proc.stdout);(out/'stderr.log').write_bytes(proc.stderr);(out/'process-exit.json').write_text(json.dumps(dict(exit=proc.returncode)))
 if proc.returncode:raise ValueError('original numeric capture failed: '+proc.stdout.decode(errors='replace')[-2500:]+proc.stderr.decode(errors='replace')[-1000:])
 value=load(out/'observations.json');value.update(owners=expected,script_sha256=hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),execution=dict(exit=proc.returncode,files={name:identity(out/name)for name in('capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json')+(()if family=='forest-edges'else('original-tests.xml',))}))
 if family=='forest-edges':value['reused_suite']=dict(path=str(cached_suite),sha256=identity(cached_suite)['sha256'])
 value['corpus_sha256']=digest(value['cases']);errors=validate_reference(value,family,repo)
 if errors:raise ValueError(errors)
 (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');return value
