"""Original dtype-aware term alignment and active source summaries."""
SCRIPT=r'''
import dataclasses,importlib,json,math,pathlib,platform,sys,unicodedata,warnings
import numpy as np,pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.alignment import TermAlignment
if not pathlib.Path(importlib.import_module('ken.retrieval.alignment').__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original alignment module')
def scalar(value):return float(value['$float'])if isinstance(value,dict)else value
def matrix(value):return np.asarray([scalar(v)for v in value['values']],dtype=value['dtype']).reshape(value['rows'],value['columns'])
def vector(value):return np.asarray([scalar(v)for v in value['values']],dtype=value['dtype'])
def clean(value):
 if dataclasses.is_dataclass(value):return clean(dataclasses.asdict(value))
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
  data=case['input']
  try:
   query=matrix(data['query']);weights=vector(data['weights']);alignment=TermAlignment(query,weights);kind=case['kind']
   if kind in ['similarities','coverage']:
    similarities=alignment.similarities(matrix(data['documents']))
    result=dict(dtype=str(similarities.dtype),rows=similarities.shape[0],columns=similarities.shape[1],values=similarities.ravel())
    if kind=='coverage':result['coverage']=alignment.summarize(similarities)
   elif kind=='summarize':result=alignment.summarize(matrix(data['similarities']))
   elif kind=='maxima':result=alignment.summarize_maxima(matrix(data['maxima']),present=np.asarray(data['present'],dtype=np.bool_))
   else:raise ValueError('unknown alignment operation')
   records.append(dict(**case,result=clean(result)))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error))))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-numeric-reference/1',family='alignment',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version,numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
