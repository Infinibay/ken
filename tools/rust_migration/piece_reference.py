"""Disjoint, authenticated original observations for source-piece responsibilities."""
from __future__ import annotations
import hashlib,json,subprocess
from pathlib import Path
from .reference import Reference,reference_env
from .selection_reference import owners
from .retrieval_reference import digest
from .native_json import identity,load
ROOT=Path(__file__).resolve().parents[2]
SUITES={'catalog':['tests/retrieval/test_piece_catalog.py']}
CATALOG_SCRIPT=r'''
import hashlib,importlib,json,pathlib,platform,sys,tempfile,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
from ken.retrieval.model import EntityKey,Passage,Span
from ken.retrieval.piece_catalog import SourceCatalog,entity_id
if not pathlib.Path(importlib.import_module('ken.retrieval.piece_catalog').__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original piece catalog')
def passage(v):return Passage(**{**v,'entity':EntityKey(**v['entity']),'span':Span(**v['span']),'entity_span':Span(**v['entity_span'])})
records=[]
for case in request['cases']:
 data=case['input']
 with tempfile.TemporaryDirectory(prefix='ken-original-piece-')as temporary:
  base=pathlib.Path(temporary);project=base/'project';project.mkdir()
  for name,content in data['files'].items():
   p=project/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(bytes(content))
  for link in data.get('symlinks',[]):
   p=project/link['path'];p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(link['target'])
  try:
   catalog=SourceCatalog(project,{EntityKey(**o['key']):[passage(p)for p in o['passages']]for o in data['owners']})
   projections=[]
   for key in catalog.owners:
    scopes=catalog.scope_members(key);enclosing=catalog.enclosing_callable(key)
    primaries={}
    for kind in ['class','module','symbol','file']:
     value=catalog.primary(key,kind);primaries[kind]=entity_id(value)if isinstance(value,EntityKey)else value
    projections.append(dict(identity=entity_id(key),extent=catalog.extent(key),owned_ranges=catalog.owned_ranges(key),implementation_ranges=catalog.owned_ranges(key,implementation=True),scope_members=[entity_id(k)for k in scopes]if scopes is not None else None,enclosing_callable=entity_id(enclosing)if enclosing else None,primary=primaries))
   records.append(dict(**case,result=dict(inventory=catalog.source_inventory(),projections=projections,lines=catalog.lines,hashes=catalog.hashes)))
  except Exception as error:records.append(dict(**case,error=dict(type=type(error).__name__,message=str(error).replace(str(project),'{project}').replace(str(base),'{scenario}'))))
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
value=dict(format='ken-piece-reference/1',family=request['family'],cases=records,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),unicode=unicodedata.unidata_version),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');sys.exit(exit_code)
'''
SCRIPTS={'catalog':CATALOG_SCRIPT}
def definitions(family:str,repo:Path=ROOT):return load(repo/f'crates/ken-retrieval/tests/fixtures/piece-inputs-{family}.json')['cases']
def validate_reference(value:dict,family:str,repo:Path=ROOT):
 try:
  def require(ok,message):
   if not ok:raise ValueError(message)
  require(value['format']=='ken-piece-reference/1'and value['family']==family,'original piece family differs')
  require(value['script_sha256']==hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),'original piece observer differs')
  require([{k:c[k]for k in('id','kind','input')}for c in value['cases']]==definitions(family,repo),'original piece input inventory differs')
  require(all(('result'in c)^('error'in c)for c in value['cases'])and digest(value['cases'])==value['corpus_sha256'],'original piece observations differ')
  require(value['execution']['exit']==0 and value['original_test_exit']==0,'original piece process/suite failed')
  found=value['discovered'];states=value['test_states'];require(found and len(set(found))==len(found),'original piece discovery absent/duplicated')
  require({s['nodeid']for s in states}==set(found)and all(s['when']=='call'and s['outcome']=='passed'for s in states),'original piece suite incomplete')
  return[]
 except(KeyError,ValueError,TypeError)as error:return[str(error)]
def capture(reference:Reference,out:Path,repo:Path=ROOT,family:str='catalog'):
 expected=owners(repo)
 for name,sha in expected.items():
  if identity(reference.root/name)['sha256']!=sha:raise ValueError('original piece owner changed: '+name)
 if(out/'reference.json').exists():
  value=load(out/'reference.json');errors=validate_reference(value,family,repo)
  if errors or value['owners']!=expected:raise ValueError(errors or'original piece owner inventory differs')
  return value
 out.mkdir(parents=True,exist_ok=False);(out/'capture.py').write_text(SCRIPTS[family])
 request=dict(root=str(reference.root),family=family,cases=definitions(family,repo),suite=SUITES[family],junit=str(out/'original-tests.xml'),result=str(out/'observations.json'))
 (out/'request.json').write_text(json.dumps(request,ensure_ascii=True))
 proc=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
 (out/'stdout.log').write_bytes(proc.stdout);(out/'stderr.log').write_bytes(proc.stderr);(out/'process-exit.json').write_text(json.dumps(dict(exit=proc.returncode)))
 if proc.returncode:raise ValueError('original piece capture failed: '+proc.stdout.decode(errors='replace')[-2000:]+proc.stderr.decode(errors='replace')[-1000:])
 value=load(out/'observations.json');value.update(owners=expected,script_sha256=hashlib.sha256(SCRIPTS[family].encode()).hexdigest(),execution=dict(exit=proc.returncode,files={name:identity(out/name)for name in('capture.py','request.json','observations.json','stdout.log','stderr.log','process-exit.json','original-tests.xml')}))
 value['corpus_sha256']=digest(value['cases']);errors=validate_reference(value,family,repo)
 if errors:raise ValueError(errors)
 (out/'reference.json').write_text(json.dumps(value,ensure_ascii=True,allow_nan=False)+'\n');return value
