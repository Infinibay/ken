"""Record original indexing boundaries in an isolated, content-verified oracle."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
from .reference import Reference,reference_env
SOURCE_SUITE=['tests/retrieval/test_passages.py','tests/retrieval/test_tokenization.py']
SOURCE_SCRIPT=r'''
import dataclasses,functools,hashlib,importlib,json,pathlib,platform,random,sys,unicodedata
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
passages=importlib.import_module('ken.retrieval.passages');vocab=importlib.import_module('ken.retrieval.tokenization');names=importlib.import_module('ken.nametokens')
from ken.parsers.types import ParsedFile,ParsedScope,ParsedSymbol,ParsedImport
for m in (passages,vocab,names):
 if not pathlib.Path(m.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original module')
def encoded(v):return json.dumps(v,ensure_ascii=True,separators=(',',':'))
def identity(v):return hashlib.sha256(encoded(v).encode()).hexdigest()
records={};discovered=[];states=[];active=None
original=passages.extract_passages
@functools.wraps(original)
def observed(source,parsed,*,path,policy=None,language='text'):
 policy=policy or passages.PassagePolicy()
 if policy.count_tokens is not passages.lexical_token_count:raise ValueError('unrecorded tokenizer')
 data=dict(source_hex=source.hex(),parsed=dataclasses.asdict(parsed),path=path,language=language,max_tokens=policy.max_tokens,tokenizer_version=policy.tokenizer_version)
 result=original(source,parsed,path=path,policy=policy,language=language);key=identity(data)
 records[key]=dict(id=key,input=data,result=[dataclasses.asdict(p)for p in result],test=active)
 return result
passages.extract_passages=observed
class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(i.nodeid for i in session.items)
 def pytest_runtest_setup(self,item):
  global active
  active=item.nodeid
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))
exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],'--junitxml='+request['junit']],plugins=[Plugin()]);active=None
for corpus in request['parser_corpora']:
 for row in json.loads(pathlib.Path(corpus).read_bytes())['cases']:
  if 'parsed'not in row or'input'not in row:continue
  data=row['input'];p=row['parsed']
  parsed=ParsedFile(symbols=[ParsedSymbol(**s)for s in p['symbols']],imports=[ParsedImport(**i)for i in p['imports']],docstring=p['docstring'],scopes=[ParsedScope(**{**s,'symbol':ParsedSymbol(**s['symbol'])})for s in p['scopes']])
  for budget in (6,256):observed(bytes.fromhex(data['source_hex']),parsed,path=data['hint'],language=data['language'],policy=passages.PassagePolicy(max_tokens=budget))
for source in ('a\r\nb\rc\nd\v\f\x1c\x1d\x1e\x85\u2028\u2029last','\n','\r\n','   ','','\x1c','\u200b','x'*1000):
 observed(source.encode(),ParsedFile(),path='docs/input.txt',policy=passages.PassagePolicy(3))
for doc in ('full docs','\ud800','\udc00'):
 symbol=ParsedSymbol('function','same','same',1,2,None)
 parsed=ParsedFile(scopes=[ParsedScope(symbol=symbol,signature='same()',documentation=doc),ParsedScope(symbol=symbol,signature='other()',documentation='second')])
 observed(b'same()\nbody\n',parsed,path='tests/owner.rs',language='rust')
texts=['HTTPServer.get_status HTTPServer.get_status','the The THE é É _ __ parseXML2JSON','scheduler scheduling parsear parsea parseo archivo fichero codigo código clase class code file','Straße ﬀ İ ı ẞ Σ ς K Å ① Ｃａｃｈｅ cafe\u0301','_HTTPServer.$foo/a-b.c_d x__y 123_𞓐Z A\u1c89 A\U00001c89 A\U0001e4d0','readHTTP2JSON9XML fooURLBar HTTP XML2JSON __a abc-123 def/foo bar.$baz']
random.seed(731)
for _ in range(180):texts.append(''.join(random.choice('abXYZ012_.-/$ éßİΣ\u0301𞓐')for _ in range(random.randrange(1,128))))
for point in (0x1c89,0x1c8a,0xa7cb,0x10d40,0x16d40,0x1e4d0,0x11f02,0x1c90,0x10400):texts.append('prefix'+chr(point)+'Suffix')
vocabulary=[]
for text in texts:
 data=dict(text=text,extra_stopwords=['cache','http'])
 vocabulary.append(dict(id=identity(data),input=data,code_tokens=vocab.code_tokens(text),terms=[dict(limit=limit,result=vocab.code_terms(text,limit=limit))for limit in (None,0,1,3,128)],name_tokens=sorted(names.name_tokens(text,extra_stopwords=set(data['extra_stopwords']))),camel=names.split_camel(text),lexical_count=passages.lexical_token_count(text)))
fold={str(i):chr(i).casefold()for i in range(0x110000)if chr(i).casefold()!=chr(i)}
result=dict(format='ken-index-source-reference/1',vocabulary=vocabulary,passages=list(records.values()),casefold=fold,unicode_version=unicodedata.unidata_version,runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version()),discovered=discovered,test_states=states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(result,ensure_ascii=True)+'\n');sys.exit(exit_code)
'''
def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
def capture_source_reference(reference:Reference,out:Path,repo:Path)->dict:
    baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    owners={r['path']:r['sha256']for r in baseline['files']if r['path'].startswith(('src/ken/retrieval/','src/ken/nametokens.py','src/ken/parsers/'))or r['path']in SOURCE_SUITE+['tests/conftest.py']}
    for name,expected in owners.items():
        if hashlib.sha256((reference.root/name).read_bytes()).hexdigest()!=expected:raise ValueError('original owner changed: '+name)
    target=out/'source-reference.json'
    if target.exists():
        value=json.loads(target.read_bytes())
        if value['script_sha256']!=hashlib.sha256(SOURCE_SCRIPT.encode()).hexdigest()or value['owners']!=owners:raise ValueError('cached original differs')
        return value
    out.mkdir(parents=True,exist_ok=True)
    corpora=[repo/'crates/ken-syntax/tests/fixtures'/name for name in ('reference.json','parser-edges.json','review-cases.json','c-macro-digits.json')]
    request=dict(root=str(reference.root),suite=SOURCE_SUITE,junit=str(out/'original-source.xml'),result=str(target),parser_corpora=[str(p)for p in corpora])
    (out/'request.json').write_text(json.dumps(request));(out/'capture.py').write_text(SOURCE_SCRIPT)
    proc=subprocess.run([str(reference.python),str(out/'capture.py'),str(out/'request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'stdout').write_bytes(proc.stdout);(out/'stderr').write_bytes(proc.stderr)
    if proc.returncode:raise ValueError('original source capture failed: '+proc.stderr.decode(errors='replace')[-2000:]+proc.stdout.decode(errors='replace')[-2000:])
    value=json.loads(target.read_bytes());value.update(owners=owners,script_sha256=hashlib.sha256(SOURCE_SCRIPT.encode()).hexdigest(),execution=dict(exit=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),stderr_sha256=hashlib.sha256(proc.stderr).hexdigest()),parser_inputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in corpora})
    target.write_text(json.dumps(value,ensure_ascii=True)+'\n');return value
if __name__=='__main__':
    import os
    root=Path.cwd();out=root/'.superpowers/sdd/2026-10-23-rust-incremental-index/original-macos'
    value=capture_source_reference(Reference.load(Path(os.environ['KEN_RUST_REFERENCE'])),out,root)
    (root/'crates/ken-retrieval/tests/fixtures/source-reference.json').write_bytes((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8',errors='backslashreplace'))
    print(json.dumps(dict(vocabulary=len(value['vocabulary']),passages=len(value['passages']),tests=len(value['discovered']),unicode=value['unicode_version'])))

STORAGE_SCRIPT=r'''
import dataclasses,hashlib,json,pathlib,platform,sys
from ken.db import connect,init_schema
from ken.retrieval.model import Passage,EntityKey,Span
from ken.retrieval.storage import replace_file_passages,load_passage_map
from ken.retrieval.passages import PassagePolicy
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root'])
import ken.retrieval.storage as owner
if not pathlib.Path(owner.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original storage')
sources=json.loads(pathlib.Path(request['source']).read_bytes())['passages'];chosen=[];languages=set()
for row in sources:
 if not row['result']:continue
 language=row['input']['language']
 if language not in languages or row['input']['path'] in ('tests/owner.rs','docs/input.txt'):
  chosen.append(row);languages.add(language)
def snapshot(conn):
 tables={table:[list(r)for r in conn.execute('SELECT * FROM '+table+' ORDER BY '+order)]for table,order in [('ci_passages','id'),('ci_passage_terms','passage_id,field,term'),('ci_passage_lengths','passage_id,field'),('ci_retrieval_files','file_id')]}
 return dict(tables=tables,loaded=[[pid,dataclasses.asdict(p)]for pid,p in load_passage_map(conn).items()])
cases=[]
for row in chosen:
 conn=connect(pathlib.Path(':memory:'));init_schema(conn)
 data=row['input'];parsed=data['parsed'];symbols=list(parsed['symbols']);known={(s['kind'],s['qualname'],s['line_start'])for s in symbols}
 for scope in parsed['scopes']:
  s=scope['symbol'];key=(s['kind'],s['qualname'],s['line_start'])
  if key not in known:symbols.append(s);known.add(key)
 symbols.sort(key=lambda s:(s['line_start'],-s['line_end']))
 conn.execute("INSERT INTO ci_files(path,language,content_hash,mtime,indexed_at)VALUES(?,?,x'00',0,0)",(data['path'],data['language']))
 for s in symbols:conn.execute('INSERT INTO ci_symbols(file_id,kind,name,qualname,line_start,line_end,docstring)VALUES(1,?,?,?,?,?,?)',(s['kind'],s['name'],s['qualname'],s['line_start'],s['line_end'],s['docstring']))
 passages=[Passage(**{**p,'entity':EntityKey(**p['entity']),'span':Span(**p['span']),'entity_span':Span(**p['entity_span'])})for p in row['result']]
 case=dict(id=row['id'],input=dict(path=data['path'],language=data['language'],symbols=symbols,passages=row['result'],source_hash=hashlib.sha256(bytes.fromhex(data['source_hex'])).hexdigest(),max_tokens=data['max_tokens'],tokenizer_version=data['tokenizer_version']),steps=[])
 for action in ('replace','repeat','delete'):
  conn.execute('BEGIN IMMEDIATE')
  try:
   if action=='delete':conn.execute('DELETE FROM ci_files WHERE id=1');ids=[]
   else:ids=replace_file_passages(conn,1,passages,source_hash=case['input']['source_hash'],policy=PassagePolicy(data['max_tokens'],tokenizer_version=data['tokenizer_version']))
   conn.commit();result=dict(ids=ids,**snapshot(conn))
  except Exception as error:conn.rollback();result=dict(error=dict(type=type(error).__name__,message=str(error)),**snapshot(conn))
  case['steps'].append(dict(action=action,**result))
 cases.append(case);conn.close()
value=dict(format='ken-index-storage-reference/1',cases=cases,runtime=dict(system=platform.system(),python=platform.python_version()),source_sha256=hashlib.sha256(pathlib.Path(request['source']).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def capture_storage_reference(reference:Reference,out:Path,source:Path)->dict:
    target=out/'storage-reference.json'
    if target.exists():return json.loads(target.read_bytes())
    out.mkdir(parents=True,exist_ok=True)
    request=dict(root=str(reference.root),source=str(source),result=str(target))
    (out/'storage-request.json').write_text(json.dumps(request));(out/'storage-capture.py').write_text(STORAGE_SCRIPT)
    proc=subprocess.run([str(reference.python),str(out/'storage-capture.py'),str(out/'storage-request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'storage-stdout').write_bytes(proc.stdout);(out/'storage-stderr').write_bytes(proc.stderr)
    if proc.returncode:raise ValueError(proc.stderr.decode(errors='replace'))
    value=json.loads(target.read_bytes());value.update(script_sha256=hashlib.sha256(STORAGE_SCRIPT.encode()).hexdigest(),execution=dict(exit=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),stderr_sha256=hashlib.sha256(proc.stderr).hexdigest()));target.write_bytes((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8',errors='backslashreplace'));return value
