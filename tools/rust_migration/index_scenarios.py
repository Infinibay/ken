"""Independent operation histories for original and native incremental indexers."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
from .reference import Reference,reference_env
from .index_reference import digest
SUITE=['tests/retrieval/test_incremental_indexing.py','tests/retrieval/test_storage.py','tests/test_nametokens.py']
def scenario_definitions(repo:Path)->list[dict]:
    cases=[]
    def w(path,text):return dict(op='write',path=path,source_hex=(text if isinstance(text,bytes)else text.encode()).hex())
    def i(paths,**kwargs):return dict(op='index',paths=paths,**kwargs)
    def add(name,ops):cases.append(dict(id=name+':'+digest(ops),operations=ops))
    base=[w('pkg/util.py','def helper():\n    """Read cache state."""\n    return 1\n'),w('app.py','import pkg.util\ndef outer():\n    def inner(): return 1\n    return inner\n'),w('README.md','# IndexProject\nInstall the parser.\n'),w('pkg%/nested.py','def nested():return 3\n'),w('pkgA/kept.py','def kept():return 4\n')]
    names=['app.py','README.md','pkg/util.py','pkg%/nested.py','pkgA/kept.py']
    add('mixed',base+[i(names,embed=True),i(names,embed=True),w('app.py','import pkg.util\ndef changed():\n    """New source intent."""\n    return "cookie"\n'),i(['app.py'],embed=True),dict(op='delete',path='pkg',subtree=True),i(['app.py']),dict(op='invalidate',name_token_version='0',clear_tokens=True),i(['app.py']),i(['app.py'],policy=dict(max_tokens=8,tokenizer_version='custom-policy')),dict(op='delete',path='pkg%',subtree=True)])
    originals=json.loads((repo/'crates/ken-index/tests/fixtures/publication-reference.json').read_bytes())['cases'];languages=[c['input']for c in originals if c['input']['language']is not None]
    add('languages',[dict(op='write',path=c['path'],source_hex=c['source_hex'])for c in languages]+[i([c['path']for c in languages])])
    errors=json.loads((repo/'crates/ken-syntax/tests/fixtures/parser-errors.json').read_bytes())['cases']
    add('header-errors',[w('api.h','namespace sample { class Reader { public: int read() { return 1; } }; }\n'),w('c_api.h','int ordinary(void);\n'),dict(op='write',path='broken.ts',source_hex=errors[0]['source_hex']),w('opaque.bin',b'\x95bad\xff\n'),w('zero.input',b'PNG\x00\xff'),w('big.py','x=1\n'*512),i(['api.h','c_api.h','broken.ts','opaque.bin','zero.input','missing.py','big.py'],max_file_bytes=512),i(['api.h']),dict(op='invalidate',parser_version=9),i(['api.h'])])
    spec=dict(model_id='provided',revision='a'*40,backend='provided')
    def profile(tokenizer='code-lexical-v1'):return dict(identity=spec,behavior=spec,max_tokens=64,passage_tokenizer=tokenizer)
    prefix=[w('client.py','def save(jar):\n    return jar\n'),w('other.py','def stable():\n    return "unrelated"\n')]
    for label,actual in [('profile-lexical',False),('profile-actual-tokenizer',True)]:
        p=profile('behavior-model'if actual else'code-lexical-v1');add(label,prefix+[i(['client.py','other.py'],profile=p,prepare=True,characters=actual),i(['client.py'],characters=actual,fail_load=True),w('client.py','def save(jar):\n'+'    jar.store("cookie")\n'*18),i(['client.py'],characters=actual)])
    for label,control in [('encoding-failure',dict(fail_encode=True)),('source-race',dict(race=dict(kind='source',path='client.py',source_hex=b'def newer():\n    return 2\n'.hex()))),('profile-race',dict(race=dict(kind='profile',fingerprint='concurrent-profile'))),('nonfinite-behavior',dict(nan_behavior=True))]:
        add(label,prefix+[i(['client.py','other.py'],profile=profile(),prepare=True),w('client.py','def save(jar):\n    return "cookie"\n'),i(['client.py'],**control)])
    writes=[w(f'm{n}.py',f'"""Module {n}."""\ndef f{n}():\n    """Read entry {n}."""\n    return {n}\n')for n in range(5)];names=[f'm{n}.py'for n in range(5)]
    add('mapped-chunks',writes+[i(names,embed=True,mapped=True,chunk_files=2),i(names,embed=True,mapped=True,chunk_files=2),w('m0.py','"""Updated module."""\ndef changed():return 9\n'),i(['m0.py'],embed=True,mapped=True),w('m0.py','def latest():return 10\n'),i(['m0.py'],embed=True,mapped=True),dict(op='delete',path='m1.py'),i(names[2:],embed=True,mapped=True)])
    add('inline-fallback',[w('cache.py','def cache():return 1\n'),dict(op='block_vectors',blocked=True),i(['cache.py'],embed=True,mapped=True),dict(op='block_vectors',blocked=False),i(['cache.py'],embed=True,mapped=True)])
    add('workload-100',[w(f'pkg/m{n}.py',f'def read_{n}(value):\n    return value + {n}\n')for n in range(100)]+[i([f'pkg/m{n}.py'for n in range(100)])])
    return cases
SCRIPT=r'''
import dataclasses,hashlib,json,os,pathlib,platform,shutil,sys,tempfile
import numpy as np
import pytest
import tree_sitter_language_pack as pack
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root']);pack.configure({'cache_dir':request['grammar_cache']})
import ken.indexer as ix
import ken.embedder as embedder
from ken.db import connect,init_schema
from ken.retrieval import indexing,representations
from ken.retrieval.profile import RetrievalProfile
from ken.retrieval.passages import PassagePolicy,lexical_token_count
from ken.retrieval.storage import load_passage_map
from ken.vectors import VectorStore
for m in (ix,embedder,indexing,representations):
 if not pathlib.Path(m.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original module')
discovered=[];states=[]
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])
ix.time.time=lambda:1700000000.0
embedder.active_model=lambda:'provided-deterministic'
original_open=ix._open_stores
class Encoder:
 dim=3
 def __init__(self,root,conn):self.root=root;self.conn=conn;self.calls=[];self.loads=0;self.characters=False;self.fail_encode=False;self.fail_load=False;self.nan_behavior=False;self.race=None;self.mapped=False;self.fallback=False
 def load(self,spec):
  self.loads+=1
  if self.fail_load:raise RuntimeError('encoder load unavailable')
  return self
 def token_count(self,text):return len(text)if self.characters else lexical_token_count(text)
 def embed_passages(self,texts):
  self.calls.append(list(texts))
  if self.fail_encode:raise RuntimeError('encoding unavailable')
  out=[]
  for text in texts:
   if self.nan_behavior and'\nSource:\n'in text:out.append(np.array([np.nan,1.,0.],dtype=np.float32));continue
   b=text.encode();v=np.array([sum(b)%31+1,len(b)%23+1,sum((i+1)*n for i,n in enumerate(b))%19+1],dtype=np.float32);out.append(v/np.linalg.norm(v))
  race=self.race;self.race=None
  if race:
   if race['kind']=='source':write(self.root,race['path'],race['source_hex'])
   else:self.conn.execute("UPDATE meta SET value=? WHERE key='retrieval_profile_fingerprint'",(race['fingerprint'],))
  return out
 def open(self,conn,root,encoder):
  if not self.mapped:return None
  stores=original_open(conn,root,encoder)
  if encoder is not None and stores is None:self.fallback=True
  return stores
def write(root,path,source):
 target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(bytes.fromhex(source));os.utime(target,ns=(1234567890000000000,1234567890000000000))
def failure(error):return dict(type=type(error).__name__,message=str(error))
def snapshot(conn,project):
 tables={}
 for table,order in [('ci_files','id'),('ci_symbols','id'),('ci_imports','id'),('ci_intent_sources','id'),('ci_name_tokens','kind,token,row_id'),('ci_passages','id'),('ci_passage_terms','passage_id,field,term'),('ci_passage_lengths','passage_id,field'),('ci_retrieval_files','file_id'),('ci_retrieval_embeddings','id'),('ci_passage_vectors','passage_id,view'),('ci_vec_alloc','space'),('ci_vec_free','space,slot'),('meta','key')]:tables[table]=[[{'blob_hex':v.hex()}if isinstance(v,bytes)else v for v in r]for r in conn.execute('SELECT * FROM '+table+' ORDER BY '+order)]
 legacy={}
 for space in ('ci_files','ci_symbols','ci_intent_sources'):
  out=[]
  for row in conn.execute('SELECT id,vec_slot,embedding FROM '+space+' ORDER BY id'):
   if row[1]is not None:
    try:
     store=VectorStore(project,space,dim=3,model='provided-deterministic')
     try:value=dict(vector=store.read([int(row[1])])[0].tolist())
     finally:store.close()
    except Exception as error:value=dict(error=str(error))
   elif row[2]is not None:value=dict(vector=np.frombuffer(row[2],dtype=np.float32).tolist())
   else:value=dict(vector=None)
   out.append(dict(id=row[0],slot=row[1],value=value))
  legacy[space]=out
 try:loaded=dict(passages=[[pid,dataclasses.asdict(p)]for pid,p in load_passage_map(conn).items()])
 except Exception as error:loaded=dict(error=failure(error))
 return dict(tables=tables,legacy_vectors=legacy,loaded=loaded)
cases=[]
for definition in request['definitions']:
 private=pathlib.Path(tempfile.mkdtemp(dir=request['scratch']));project=private/'IndexProject';project.mkdir();(project/'.ken').mkdir();conn=connect(project/'.ken/ken.db');init_schema(conn);encoder=Encoder(project,conn);ix._open_stores=encoder.open;indexing.load_encoder=representations.load_encoder=encoder.load;steps=[]
 for op in definition['operations']:
  events=[]
  try:
   kind=op['op']
   if kind=='write':write(project,op['path'],op['source_hex']);result=dict(written=True)
   elif kind=='remove':
    target=project/op['path'];shutil.rmtree(target)if target.is_dir()else target.unlink();result=dict(removed=True)
   elif kind=='delete':result=dict(deleted=ix.delete_path(conn,op['path'])if op.get('subtree')else ix.delete_file(conn,op['path']))
   elif kind=='invalidate':
    if op.get('parser_version')is not None:conn.execute('UPDATE ci_files SET parser_version=?',(op['parser_version'],))
    if op.get('name_token_version')is not None:conn.execute("INSERT INTO meta(key,value)VALUES('name_token_version',?)ON CONFLICT(key)DO UPDATE SET value=excluded.value",(op['name_token_version'],))
    if op.get('extractor_version')is not None:conn.execute('UPDATE ci_retrieval_files SET extractor_version=?',(op['extractor_version'],))
    if op.get('clear_tokens'):conn.execute('DELETE FROM ci_name_tokens')
    result=dict(invalidated=True)
   elif kind=='block_vectors':
    target=project/'.ken/vectors';saved=project/'.ken/vectors.saved'
    if op['blocked']:
     if target.exists():target.rename(saved)
     target.write_bytes(b'not a directory')
    else:
     target.unlink()
     if saved.exists():saved.rename(target)
    result=dict(blocked=op['blocked'])
   elif kind=='index':
    ix._EMBED_CHUNK_FILES=op.get('chunk_files',128);encoder.calls=[];encoder.loads=0;encoder.characters=op.get('characters',False);encoder.fail_encode=op.get('fail_encode',False);encoder.fail_load=op.get('fail_load',False);encoder.nan_behavior=op.get('nan_behavior',False);encoder.race=op.get('race');encoder.mapped=op.get('mapped',False);encoder.fallback=False;os.environ['KEN_INDEX_WORKERS']=str(op.get('workers',0))
    profile=RetrievalProfile.from_dict(op['profile'])if op.get('profile')is not None else None;policy=PassagePolicy(**op['policy'])if op.get('policy')is not None else None
    stats=ix.index_files(conn,project,[pathlib.Path(p)for p in op['paths']],max_file_bytes=op.get('max_file_bytes',1024*1024),on_progress=lambda p,s:events.append([p,s]),embedder=encoder if op.get('embed')else None,retrieval_profile=profile,retrieval_policy=policy)
    if op.get('prepare'):representations.index_embeddings(conn,profile)
    result=dict(stats=dataclasses.asdict(stats),events=events,encoder_calls=encoder.calls,encoder_loads=encoder.loads,storage_fallback=encoder.fallback)
   else:raise ValueError('unknown operation')
   step=dict(result=result)
  except Exception as error:step=dict(error=failure(error),events=events,encoder_calls=encoder.calls,encoder_loads=encoder.loads)
  step['snapshot']=snapshot(conn,project);steps.append(step)
 cases.append(dict(id=definition['id'],steps=steps));conn.close();shutil.rmtree(private)
value=dict(format='ken-index-scenario-reference/1',cases=cases,definitions=request['definitions'],runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),numpy=np.__version__),discovered=discovered,test_states=states,original_test_exit=exit_code,normalizations=['result.stats.elapsed_s','warnings diagnostic text'],physical_slot_contract='M2 rollback-safe allocator; audit ownership and bounded high-water separately')
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n');sys.exit(exit_code)
'''
# The initial observer ran the unchanged suite correctly, but omitted the chunk
# control in its subsequent histories. Reuse only that suite, with its exact script.
INITIAL_SCRIPT=SCRIPT.replace("ix._EMBED_CHUNK_FILES=op.get('chunk_files',128);", "")
_SUITE_LINE="exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()])"
HISTORY_SCRIPT=SCRIPT.replace(_SUITE_LINE,"exit_code=None")

def validate_document_chunks(definition:dict,case:dict)->list[str]:
    for operation,step in zip(definition['operations'],case['steps'],strict=True):
        if operation['op']!='index' or not operation.get('embed')or'result'not in step:continue
        # These provided legacy-only histories have no retrieval profile.
        if operation.get('profile'):continue
        chunk=operation.get('chunk_files',128);events=step['result']['events']
        batches=sum(any(status.startswith('indexed')for _,status in events[start:start+chunk])for start in range(0,len(events),chunk))
        if len(step['result']['encoder_calls'])!=batches:return ['original document chunks differ from requested control']
    return []

def _suite_errors(value:dict)->list[str]:
    try:
        if value['original_test_exit']!=0 or value['execution']['exit']!=0:return ['original integration suite failed']
        if not value['discovered']or len(set(value['discovered']))!=len(value['discovered']):return ['original discovery missing']
        if {s['nodeid']for s in value['test_states']}!=set(value['discovered'])or any(s['when']!='call'or s['outcome']!='passed'for s in value['test_states']):return ['original tests incomplete']
        return []
    except(KeyError,TypeError):return ['original test record incomplete']

def validate_scenario_reference(value)->list[str]:
    try:
        def require(condition,message):
            if not condition:raise ValueError(message)
        require(value['format']=='ken-index-scenario-reference/1','wrong original history format')
        reused=value.get('suite_reuse')
        if reused:
            require(value['script_sha256']==hashlib.sha256(HISTORY_SCRIPT.encode()).hexdigest(),'original history script changed')
            require(value['original_test_exit']is None and value['discovered']==value['test_states']==[],'history-only execution claimed fresh tests')
            prior=reused['reference'];require(prior['script_sha256']==hashlib.sha256(INITIAL_SCRIPT.encode()).hexdigest(),'reused suite script changed')
            require(prior['owners']==value['owners']and not _suite_errors(prior),'reused suite owners/outcomes changed')
            require(reused['reference_sha256']==hashlib.sha256((json.dumps(prior,ensure_ascii=True)+'\n').encode()).hexdigest(),'reused suite reference changed')
        else:
            require(value['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'original history script changed')
            require(not _suite_errors(value),'original integration suite incomplete')
        require(value['execution']['exit']==0,'original histories failed')
        require(len(value['cases'])==len(value['definitions'])>=12,'original histories incomplete')
        for definition,case in zip(value['definitions'],value['cases'],strict=True):
            require(definition['id'].split(':')[-1]==digest(definition['operations'])and case['id']==definition['id'],'original history input changed')
            require(len(case['steps'])==len(definition['operations']),'original operations missing')
            require(not validate_document_chunks(definition,case),'original chunk control ignored')
            require(all('snapshot'in step and (('result'in step)^('error'in step))for step in case['steps']),'incomplete original effects')
        require(value['corpus_sha256']==digest({k:value[k]for k in ('definitions','cases')}),'original history corpus changed')
        return []
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def capture_scenario_reference(reference:Reference,out:Path,repo:Path,*,reuse_suite:Path|None=None)->dict:
    definitions=scenario_definitions(repo);baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    owners={r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/retrieval/','src/ken/indexer.py','src/ken/nametokens.py','src/ken/db.py','src/ken/schema.sql','src/ken/parsers/'))or r['path']in SUITE+['tests/conftest.py']}
    for name,expected in owners.items():
        if hashlib.sha256((reference.root/name).read_bytes()).hexdigest()!=expected:raise ValueError('original owner changed: '+name)
    target=out/'scenario-reference.json'
    if target.exists():
        value=json.loads(target.read_bytes());errors=validate_scenario_reference(value)
        if errors or value['definitions']!=definitions or value['owners']!=owners:raise ValueError(errors or'original histories changed')
        return value
    out.mkdir(parents=True,exist_ok=True);scratch=out/'scenario-scratch';scratch.mkdir(exist_ok=True)
    sdk=repo/('.ken/rust-migration/m3-parsers/sdk-macos'if sys.platform=='darwin'else'.ken/rust-migration/m3-parsers/sdk-linux')
    request=dict(root=str(reference.root),definitions=definitions,suite=SUITE,junit=str(out/'original-index.xml'),result=str(target),scratch=str(scratch),grammar_cache=str(sdk))
    script=HISTORY_SCRIPT if reuse_suite else SCRIPT
    (out/'scenario-request.json').write_text(json.dumps(request));(out/'scenario-capture.py').write_text(script)
    proc=subprocess.run([str(reference.python),str(out/'scenario-capture.py'),str(out/'scenario-request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'scenario-stdout').write_bytes(proc.stdout);(out/'scenario-stderr').write_bytes(proc.stderr)
    if proc.returncode:raise ValueError(proc.stderr.decode(errors='replace')[-2000:]+proc.stdout.decode(errors='replace')[-3000:])
    value=json.loads(target.read_bytes());value.update(script_sha256=hashlib.sha256(script.encode()).hexdigest(),owners=owners,execution=dict(exit=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),stderr_sha256=hashlib.sha256(proc.stderr).hexdigest()))
    if reuse_suite:
        prior=json.loads(reuse_suite.read_bytes());value['suite_reuse']=dict(reference=prior,reference_sha256=hashlib.sha256(reuse_suite.read_bytes()).hexdigest())
    value['corpus_sha256']=digest({k:value[k]for k in ('definitions','cases')});errors=validate_scenario_reference(value)
    if errors:raise ValueError(errors)
    target.write_text(json.dumps(value,ensure_ascii=True)+'\n');return value
