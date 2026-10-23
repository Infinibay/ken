"""Observe original import SQL callers and pure structural decisions independently."""
from __future__ import annotations
import hashlib, json, os, subprocess
from pathlib import Path
from .reference import Reference, reference_env


def supplements() -> list[dict]:
    cases=[]
    def add(files, module, *, source='src/main.ts', language='typescript', configs=None, root=True):
        files=[source,*[p for p in files if p!=source]]
        cases.append(dict(files=files,configs=({k:v.encode().hex() for k,v in (configs or {}).items()} if root else None),
                          imports=[dict(module=module,source_path=source,language=language)]))
    add(['pkg/util.py'],'pkg.util',source='main.py',language='python')
    add(['a/util.py','b/util.py'],'util',source='main.py',language='python')
    add(['a/caf\u00e9.py'],'\x1ccaf\u00e9\x1f',source='main.py',language='python')
    add(['src/value.ts'],'./value.js')
    add(['src/value.ts','src/value.js'],'./value.js')
    for extension in ('.ts','.tsx','.d.ts','.js','.jsx','.mjs','.cjs'):
        add(['src/value'+extension],'./value')
        add(['src/value/index'+extension],'./value')
    add(['asset.json'],'../../asset.json')
    add([],'.missing',source='main',language=None,root=False)
    add(['pkg/value.ts','src/value.ts'],'@app/value',configs={'tsconfig.json':'{"compilerOptions":{"baseUrl":".","paths":{"@app/*":["missing/*","src/*"]}}}'})
    add(['tsconfig.json','child/tsconfig.json','shared/value.ts'],'@value',source='child/main.ts',configs={
        'tsconfig.json':'{"compilerOptions":{"paths":{"@value":["shared/value"]}}}',
        'child/tsconfig.json':'{"compilerOptions":{"paths":{"@value":["missing"]}}}'})
    add(['tsconfig.json','shared/value.ts'],'@value',configs={
        'tsconfig.json':'{"extends":"./base"}',
        'base.json':'// inherited config\n{"compilerOptions":{"baseUrl":".","paths":{"@value":["shared/value",],},},}'})
    add(['tsconfig.json'],'@missing',configs={'tsconfig.json':'{"extends":"./tsconfig","compilerOptions":{"paths":{"@missing":["none"]}}}'})
    add(['tsconfig.json','src/value.ts','pkg/value.ts'],'@value',configs={'tsconfig.json':'{"compilerOptions":{"paths":{"@value":["pkg/value"],"@value":["src/value"]}}}'})
    add(['tsconfig.json','src/value.ts'],'@value',configs={'tsconfig.json':'{"compilerOptions":{"paths":{"@value":["src/value"]}},"unused":1e999}'})
    add(['tsconfig.json','src/value.ts'],'@value',configs={'tsconfig.json':'{"compilerOptions":{"paths":{"@value":["src/value"]}},"unused":NaN}'})
    add(['tsconfig.json'],'@value',configs={'tsconfig.json':'{"compilerOptions":[1]}'})
    add(['tsconfig.json'],'@value',configs={'tsconfig.json':'{"compilerOptions":[]}'})
    add(['tsconfig.json'],'@value',configs={'tsconfig.json':'{ broken json'})
    add(['pkg/package.json','pkg/index.ts'],'@scope/pkg',configs={'pkg/package.json':'{"name":"@scope/pkg"}'})
    add(['pkg/package.json','pkg/index.ts'],'@scope/pkg',configs={'pkg/package.json':'{"name":"@scope/pkg"}'},root=False)
    add(['crate/Cargo.toml','crate/src/config.rs'],'crate::config::Value',source='crate/src/main.rs',language='rust')
    add(['Cargo.toml'],'super::*',source='src/main.rs',language='rust')
    add(['go.mod','internal/a_test.go','internal/z.go','internal/b.go'],'example.test/app/internal',source='main.go',language='go',configs={'go.mod':'module example.test/app\n'})
    add(['src/util.rb'],'./util',source='src/main.rb',language='ruby')
    add(['one/pkg/Value.java','two/pkg/Value.java'],'pkg.Value',source='main.java',language='java')
    add(['src/pkg/Value.java'],'pkg.Value.member',source='main.java',language='java')
    add(['one/shared.hpp','two/shared.hpp'],'"shared.hpp"',source='one/main.cpp',language='cpp')
    add(['vector.py'],'vector',source='main.cpp',language='cpp')
    add(['src/pkg/A.kt','src/pkg/B.kt'],'pkg.Value',source='main.kt',language='kotlin')
    add(['composer.json','lib/Value.php'],'App\\Value',source='main.php',language='php',configs={'composer.json':'{"autoload":{"psr-4":{"App\\\\":"lib/"}}}'})
    add(['composer.json'],'App\\Value',source='main.php',language='php',configs={'composer.json':'{"autoload":[1]}'})
    return cases


SCRIPT=r'''
import functools,hashlib,json,pathlib,platform,sqlite3,sys,tempfile
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root']).resolve()
import tree_sitter_language_pack as pack
pack.configure({'cache_dir':request['grammar_cache']})
import ken.indexer as indexer
import ken.jsresolve as jsresolve
for module in (indexer,jsresolve):
 if not pathlib.Path(module.__file__).resolve().is_relative_to(root):raise ValueError('wrong original import module root')
actual_resolve=indexer._resolve_internal_imports;actual_load=jsresolve._load_jsonc
observed={};active_test=None;active_configs=None;discovered=[];states=[];calls=0

def load(project,rel):
 if active_configs is not None:
  try:active_configs[rel]=(project/rel).read_bytes().hex()
  except OSError:pass
 return actual_load(project,rel)
jsresolve._load_jsonc=load

@functools.wraps(actual_resolve)
def resolve(conn,project_root=None):
 global calls,active_configs
 imports=conn.execute('SELECT i.id,i.to_module,f.path AS src,f.language AS lang FROM ci_imports i JOIN ci_files f ON f.id=i.from_file_id WHERE i.to_file_id IS NULL').fetchall()
 if not imports:return actual_resolve(conn,project_root)
 calls+=1
 files=[r['path']for r in conn.execute('SELECT id,path FROM ci_files')]
 configs=None if project_root is None else {}
 if configs is not None:
  for path in files:
   if path.endswith(('go.mod','composer.json')):
    try:configs[path]=(project_root/path).read_bytes().hex()
    except OSError:pass
 inputs=[dict(module=r['to_module'],source_path=r['src'],language=r['lang'])for r in imports]
 structural=[indexer._resolve_import_target(r['module'],files,source_path=r['source_path'])for r in inputs]
 old=active_configs;active_configs=configs
 error=None
 try:actual_resolve(conn,project_root)
 except Exception as failure:error=dict(type=type(failure).__name__,message=str(failure))
 finally:active_configs=old
 definition=dict(files=files,configs=configs,imports=inputs)
 identity=hashlib.sha256(json.dumps(definition,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
 result=dict(id=identity,input=definition,structural_targets=structural,tests=[active_test]if active_test else[],calls=1)
 if error is not None:result['error']=error
 else:
  values={r['id']:dict(target=r['target'],resolution=r['resolution'])for r in conn.execute('SELECT i.id,f.path AS target,i.resolution FROM ci_imports i LEFT JOIN ci_files f ON f.id=i.to_file_id')}
  result['results']=[values[r['id']]for r in imports]
 if identity in observed:
  existing=observed[identity]
  if {k:v for k,v in result.items()if k not in ('tests','calls')}!={k:v for k,v in existing.items()if k not in ('tests','calls')}:raise ValueError('nondeterministic original resolution')
  existing['calls']+=1
  if active_test and active_test not in existing['tests']:existing['tests'].append(active_test)
 else:observed[identity]=result
 if error is not None:raise RuntimeError('observed original resolution error: '+str(error))
indexer._resolve_internal_imports=resolve

class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(item.nodeid for item in session.items)
 def pytest_runtest_setup(self,item):
  global active_test
  active_test=item.nodeid
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q','tests/test_indexer.py','--junitxml='+request['junit']],plugins=[Plugin()])
active_test=None
for definition in request['supplements']:
 with tempfile.TemporaryDirectory(prefix='ken-original-import-')as directory:
  project=pathlib.Path(directory)
  for path,raw in (definition['configs']or{}).items():
   target=project/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes.fromhex(raw))
  conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
  conn.executescript('CREATE TABLE ci_files(id INTEGER PRIMARY KEY,path TEXT,language TEXT); CREATE TABLE ci_imports(id INTEGER PRIMARY KEY,from_file_id INTEGER,to_module TEXT,to_file_id INTEGER,resolution TEXT);')
  languages={r['source_path']:r['language']for r in definition['imports']}
  for i,path in enumerate(definition['files'],1):conn.execute('INSERT INTO ci_files VALUES(?,?,?)',(i,path,languages.get(path)))
  ids={r['path']:r['id']for r in conn.execute('SELECT id,path FROM ci_files')}
  for i,row in enumerate(definition['imports'],1):conn.execute('INSERT INTO ci_imports(id,from_file_id,to_module)VALUES(?,?,?)',(i,ids[row['source_path']],row['module']))
  try:resolve(conn,None if definition['configs']is None else project)
  except RuntimeError:pass
  conn.close()
result=dict(format='ken-import-reference/1',cases=list(observed.values()),calls=calls,discovered=discovered,test_states=states,original_test_exit=exit_code,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()))
pathlib.Path(request['result']).write_text(json.dumps(result,ensure_ascii=True)+'\n')
sys.exit(exit_code)
'''


def import_owner_hashes(repo:Path)->dict[str,str]:
    baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    selected={'src/ken/indexer.py','src/ken/jsresolve.py','tests/test_indexer.py','tests/conftest.py'}
    return {r['path']:r['sha256']for r in baseline['files']if r['path']in selected}

def cases_digest(cases:list)->str:
    return hashlib.sha256(json.dumps(cases,sort_keys=True,ensure_ascii=True).encode()).hexdigest()

def validate_import_reference(value:dict)->list[str]:
    try:
        def require(condition,message):
            if not condition:raise ValueError(message)
        require(value['format']=='ken-import-reference/1','wrong original import protocol')
        require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'original import script differs')
        require(value['supplements_sha256']==cases_digest(supplements()),'supplement inputs differ')
        cases=value['cases'];ids=[]
        require(bool(cases)and value['cases_sha256']==cases_digest(cases),'original import cases changed/missing')
        for row in cases:
            identity=hashlib.sha256(json.dumps(row['input'],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
            require(row['id']==identity,'original import identity differs');ids.append(identity)
            count=len(row['input']['imports'])
            require(count>0 and len(row['structural_targets'])==count,'lost structural inputs')
            require(('error'in row)!=('results'in row),'result/error boundary differs')
            if 'results'in row:
                require(len(row['results'])==count and all(r['resolution']in ('internal','unresolved','external')for r in row['results']),'incomplete import results')
        require(len(ids)==len(set(ids))and sum(c['calls']for c in cases)==value['calls'],'original inventory differs')
        require(value['original_test_exit']==0 and value['test_execution']['exit']==0,'actual original indexer tests failed')
        discovered=value['discovered'];states=value['test_states']
        require(len(discovered)>=30 and len(set(discovered))==len(discovered),'original indexer discovery differs')
        require({r['nodeid']for r in states}==set(discovered)and all(r['when']=='call'and r['outcome']=='passed'for r in states),'original indexer test states differ')
        return []
    except (ValueError,KeyError,TypeError)as error:return[str(error)]

def capture_import_reference(reference:Reference,out:Path,*,repo:Path)->dict:
    owners=import_owner_hashes(repo)
    for name,expected in owners.items():
        if not(reference.root/name).is_file()or hashlib.sha256((reference.root/name).read_bytes()).hexdigest()!=expected:raise ValueError('original import owner changed: '+name)
    if(out/'reference.json').exists():
        value=json.loads((out/'reference.json').read_bytes())
        if value['owners']!=owners or validate_import_reference(value):raise ValueError('stale original import reference')
        return value
    import tree_sitter_language_pack as pack
    cache=Path(os.environ.get('KEN_IMPORT_ORIGINAL_GRAMMARS',pack.cache_dir())).resolve()
    out.mkdir(parents=True,exist_ok=True);out=out.resolve()
    request=dict(root=str(reference.root),grammar_cache=str(cache),junit=str(out/'original-tests.xml'),result=str(out/'original-observations.json'),supplements=supplements())
    (out/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    execution=subprocess.run([str(reference.python),'-c',SCRIPT,str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True,timeout=120,check=False)
    (out/'stdout.log').write_bytes(execution.stdout);(out/'stderr.log').write_bytes(execution.stderr)
    if execution.returncode:raise ValueError('original indexer resolution capture failed: '+execution.stdout[-3000:].decode(errors='replace')+'\n'+execution.stderr[-1500:].decode(errors='replace'))
    raw=(out/'original-observations.json').read_bytes()
    value=json.loads(raw)
    value.update(owners=owners,script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),supplements_sha256=cases_digest(supplements()),cases_sha256=cases_digest(value['cases']),test_execution=dict(exit=execution.returncode,python=str(reference.python),cwd=str(reference.root),stdout_sha256=hashlib.sha256(execution.stdout).hexdigest(),stderr_sha256=hashlib.sha256(execution.stderr).hexdigest(),observations_sha256=hashlib.sha256(raw).hexdigest(),timeout_s=120))
    errors=validate_import_reference(value)
    if errors:raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(value,indent=2)+'\n')
    return value
