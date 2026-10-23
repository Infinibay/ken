"""Capture actual frozen common-model calls without native-produced expectations."""
from __future__ import annotations
from collections import Counter
import hashlib,json,os,subprocess
from pathlib import Path
from .reference import Reference,reference_env
SUITE=['tests/common_ast/test_normalization.py','tests/common_ast/test_scopes.py','tests/common_ast/test_language_features.py','tests/structural/test_type_refs.py']
SCRIPT=r'''
import copy,dataclasses,functools,hashlib,importlib,json,pathlib,platform,re,sys,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root']).resolve()
import tree_sitter_language_pack as pack
pack.configure({'cache_dir':request['grammar_cache']})
model=importlib.import_module('ken.common_ast.model');normal=importlib.import_module('ken.common_ast.normalize')
bindings=importlib.import_module('ken.common_ast.symbols');types=importlib.import_module('ken.structural.type_refs')
common=importlib.import_module('ken.common_ast');kinds=importlib.import_module('ken.common_ast.kinds')
from ken.common_ast.environment import Environment
from ken.common_ast.boundaries import body_ranges
from ken.structural.model import IR,Entity,Operation,Fact
for module in (model,normal,bindings,types,common,kinds):
 if not pathlib.Path(module.__file__).resolve().is_relative_to(root):raise ValueError('wrong original module root')
programs={};type_cases={};codecs={};prebinding={};calls=0;active=None;discovered=[];states=[]
def encoded(value):return json.dumps(value,ensure_ascii=True,separators=(',',':'))
def identity(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def failure(error):return dict(type=type(error).__name__,message=str(error))
def query(program,name,scope,point):
 try:return dict(result=dataclasses.asdict(Environment(program.scopes,program.symbols,language=program.language).resolve(name,scope,point)))
 except Exception as error:return dict(error=failure(error))
original_bind=bindings.bind
@functools.wraps(original_bind)
def observed_bind(ir,nodes,scopes):
 prebinding[identity(ir.to_dict())]=dict(nodes=[dataclasses.asdict(n)for n in nodes],scopes=[dataclasses.asdict(s)for s in scopes])
 return original_bind(ir,nodes,scopes)
bindings.bind=observed_bind
original_type=types.parse_type
@functools.wraps(original_type)
def observed_type(annotation,language,depth=0):
 result=original_type(annotation,language,depth)
 if depth==0:
  data=dict(annotation=annotation,language=language);key=identity(data)
  value=dict(id=key,input=data,result=dataclasses.asdict(result))
  if key in type_cases and type_cases[key]!=value:raise ValueError('nondeterministic original type')
  type_cases[key]=value
 return result
types.parse_type=normal.parse_type=bindings.parse_type=observed_type
original_decode=model.Program.from_dict
@functools.wraps(original_decode)
def observed_decode(cls,data):
 key=identity(data);row=dict(id=key,input=copy.deepcopy(data))
 try:
  result=original_decode(data);row['result']=result.to_dict();return result
 except Exception as error:row['error']=failure(error);raise
 finally:codecs[key]=row
model.Program.from_dict=classmethod(observed_decode)
original_normalize=normal.normalize
@functools.wraps(original_normalize)
def observed_normalize(ir):
 global calls
 calls+=1;data=ir.to_dict();key=identity(data);row=dict(id=key,input=data,tests=[active]if active else[],calls=1)
 try:
  result=original_normalize(ir);row['result']=result.to_dict()
  row['prebinding']={**result.to_dict(),**prebinding[key], 'symbols':[], 'references':[]}
  row['bodies']=[{**dataclasses.asdict(body),'final_node':body.final_node}for body in body_ranges(result)]
  lookups=[];queries=set()
  for ref in result.references:queries.add((ref.name,ref.scope,result.nodes[ref.node].start))
  for symbol in result.symbols:
   for point in (0,max(0,symbol.visible_from-1),symbol.visible_from,symbol.initialized_from or 0):queries.add((symbol.name,symbol.scope,point))
  for scope in result.scopes:queries.add(('__missing__',scope.id,0))
  for name,scope,point in sorted(queries):lookups.append(dict(name=name,scope=scope,point=point,**query(result,name,scope,point)))
  for scope,point in ((-1,0),(len(result.scopes),0),(0,-1)):
   lookups.append(dict(name='missing',scope=scope,point=point,**query(result,'missing',scope,point)))
  row['lookups']=lookups
  if key in programs:
   previous=programs[key]
   if previous.get('result')!=row['result']:raise ValueError('nondeterministic original program')
   previous['calls']+=1
   if active and active not in previous['tests']:previous['tests'].append(active)
  else:programs[key]=row
  return result
 except Exception as error:
  row['error']=failure(error);programs[key]=row;raise
normal.normalize=common.normalize=observed_normalize
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(item.nodeid for item in session.items)
 def pytest_runtest_setup(self,item):
  global active
  active=item.nodeid
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
active=None
for language in ('python','javascript','typescript','java','csharp','cpp','go','rust','ruby'):
 for annotation in ('',' : int ','Vec<list[str | None]>','const User* volatile','User *const volatile','int (*)(int)','int[,,]','[u8; 2+2]',"&'life mut User",'map[string][]*User','list['*40+'int'+']'*40,'A'*10001,'π','A\u0301','A\U0001e4d0','A\U00001c89'):
  observed_type(annotation,language)
# Direct graph cases exercise actual normalize without invoking a parser again.
def op(key,parent=None,start=0,end=10,native='module',kind='UNKNOWN',role='',attrs=None):
 return Operation(key,kind,native,parent,role,start,end,1,'owner',attrs or {})
graphs=[IR('empty','python'),IR('unknown','python',operations=[op('root'),op('child','root',native='unfamiliar',attrs={'unused':'\ud800'})]),
 IR('forest','python',operations=[op('z',start=0,end=20),op('b','z',start=1,end=2,native='integer',attrs={'text':'1'}),op('a','z',start=1,end=2,native='integer',attrs={'text':'2'}),op('other','missing',start=30,end=31)]),
 IR('cycle','python',operations=[op('a','b'),op('b','a')]),
 IR('duplicate','python',operations=[op('root'),op('a','root',start=1,end=2),op('a','root',start=1,end=2)])]
for reverse in (False,True):
 entities=[Entity('z','CLASS','first','ordered',1,1,{'start_byte':1,'end_byte':2,'native_kind':'class_definition'}),Entity('a','CLASS','second','ordered',1,1,{'start_byte':1,'end_byte':2,'native_kind':'class_definition'})]
 if reverse:entities.reverse()
 graphs.append(IR('ordered','python',entities={e.id:e for e in entities},operations=[op('root'),op('type','root',start=1,end=2,native='class_definition')]))
for graph in graphs:
 try:observed_normalize(graph)
 except Exception:pass
base=next(row['result']for row in programs.values()if row.get('result',{}).get('nodes'))
for field,value in [('version','future'),('nodes',[]),('scopes',[]),('symbols',[]),('references',[]),('links',[])]:
 data=copy.deepcopy(base);data[field]=value
 try:observed_decode(model.Program,data)
 except Exception:pass
for field,value in [('id',99),('parent',99),('start',-1),('end',-1),('scope',99),('subtree_end',0),('ordinal',-1)]:
 data=copy.deepcopy(base);data['nodes'][min(1,len(data['nodes'])-1)][field]=value
 try:observed_decode(model.Program,data)
 except Exception:pass
# Default fields are constructor behavior, not a new format version.
data=copy.deepcopy(base)
for group,required in [('nodes',14),('scopes',7),('symbols',8),('references',6),('links',3)]:
 constructor={'nodes':model.Node,'scopes':model.Scope,'symbols':model.Symbol,'references':model.Reference,'links':model.Link}[group]
 optional={f.name for f in dataclasses.fields(constructor)if f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING}
 for row in data[group]:
  for field in optional:row.pop(field,None)
# subtree_end defaults to0 and therefore validation rejects nonempty nodes.
try:observed_decode(model.Program,data)
except Exception:pass
word_ranges=[];start=None
for point in range(0x110000):
 word=bool(re.fullmatch(r'\w',chr(point)))
 if word and start is None:start=point
 if start is not None and(not word or point==0x10ffff):word_ranges.append([start,point-1 if not word else point]);start=None
result=dict(format='ken-program-reference/1',programs=list(programs.values()),types=list(type_cases.values()),codecs=list(codecs.values()),calls=calls,
 vocabulary=dict(native=kinds.NATIVE,operations=kinds.OPERATIONS,unicode_version=unicodedata.unidata_version,word_ranges=word_ranges),
 runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(result,ensure_ascii=True)+'\n');sys.exit(exit_code)
'''
def _hash(value):return hashlib.sha256(json.dumps(value,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
def program_owner_hashes(repo:Path)->dict:
    baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    return {r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/common_ast/','src/ken/structural/','tests/common_ast/'))or r['path']in('tests/structural/test_type_refs.py','tests/conftest.py')}
def validate_program_reference(value:dict)->list[str]:
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(value['format']=='ken-program-reference/1'and value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'wrong original program capture')
        require(value['original_test_exit']==value['execution']['exit']==0,'original program suite failed')
        require(len(value['discovered'])==len(set(value['discovered']))and bool(value['discovered']),'invalid original test discovery')
        require({s['nodeid']for s in value['test_states']}==set(value['discovered'])and all(s['when']=='call'and s['outcome']=='passed'for s in value['test_states']),'original test states differ')
        for group in ('programs','types','codecs'):
            rows=value[group];require(bool(rows)and len({r['id']for r in rows})==len(rows),'lost/duplicate original '+group)
            for row in rows:
                require(row['id']==_hash(row['input'])and(('error'in row)^('result'in row)),'original input/result differs')
                if group=='programs'and'result'in row:require(set(row['result'])=={'path','language','nodes','scopes','symbols','references','links','diagnostics','version'}and all(k in row for k in ('prebinding','bodies','lookups')),'incomplete original program')
        require(value['corpus_sha256']==_hash({k:value[k]for k in ('programs','types','codecs','vocabulary')}),'original corpus changed')
        return []
    except(ValueError,KeyError,TypeError)as error:return[str(error)]
def capture_program_reference(reference:Reference,out:Path,*,repo:Path|None=None)->dict:
    repo=repo or Path.cwd();owners=program_owner_hashes(repo)
    for name,digest in owners.items():
        if hashlib.sha256((reference.root/name).read_bytes()).hexdigest()!=digest:raise ValueError('changed original '+name)
    destination=out/'reference.json'
    if destination.is_file():
        value=json.loads(destination.read_bytes());errors=validate_program_reference(value)
        if errors or value['owners']!=owners:raise ValueError(errors or'original owners changed')
        return value
    out.mkdir(parents=True,exist_ok=True)
    request=dict(root=str(reference.root),grammar_cache=str(repo/('.ken/rust-migration/m3-parsers/sdk-macos'if __import__('sys').platform=='darwin'else'.ken/rust-migration/m3-parsers/sdk-linux')),suite=SUITE,junit=str((out/'original-tests.xml').absolute()),result=str((out/'original-observations.json').absolute()))
    (out/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    result=subprocess.run([str(reference.python),'-c',SCRIPT,str((out/'request.json').absolute())],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=120,check=False)
    (out/'stdout.log').write_bytes(result.stdout);(out/'stderr.log').write_bytes(result.stderr)
    if not(out/'original-observations.json').is_file():raise ValueError('original capture failed: '+result.stderr.decode()[-3000:])
    value=json.loads((out/'original-observations.json').read_bytes());value.update(owners=owners,script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),execution=dict(exit=result.returncode,stdout_sha256=hashlib.sha256(result.stdout).hexdigest(),stderr_sha256=hashlib.sha256(result.stderr).hexdigest(),observations_sha256=hashlib.sha256((out/'original-observations.json').read_bytes()).hexdigest()))
    value['corpus_sha256']=_hash({k:value[k]for k in ('programs','types','codecs','vocabulary')});errors=validate_program_reference(value)
    if errors:raise ValueError(str(errors)+'\n'+result.stdout.decode()[-3000:]+result.stderr.decode()[-3000:])
    destination.write_text(json.dumps(value,indent=2)+'\n');return value
