"""Immutable observer for complete source-owner descriptions."""
SCRIPT=r'''
import dataclasses,importlib,json,pathlib,platform,sys,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Span,Passage
from ken.retrieval.description import describe_owner
for name in ['description','model']:
 if not pathlib.Path(importlib.import_module('ken.retrieval.'+name).__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original owner module')
def p(value):
 value=dict(value);value['entity']=EntityKey(**value['entity']);value['span']=Span(**value['span']);value['entity_span']=Span(**value['entity_span']);return Passage(**value)
records=[]
for case in request['cases']:
 try:records.append(dict(**case,result=dataclasses.asdict(describe_owner([p(v)for v in case['input']['passages']]))))
 except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error))))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-selection-reference/1',family='owners',cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
