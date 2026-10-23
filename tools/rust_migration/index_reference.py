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

PUBLICATION_SCRIPT=r'''
import dataclasses,hashlib,json,pathlib,platform,shutil,sys,tempfile
import numpy as np
import tree_sitter_language_pack as pack
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes());root=pathlib.Path(request['root']);pack.configure({'cache_dir':request['grammar_cache']})
from ken.db import connect,init_schema
import ken.indexer as ix
if not pathlib.Path(ix.__file__).resolve().is_relative_to(root.resolve()):raise ValueError('wrong original indexer')
ix.time.time=lambda:1700000000.0
class Encoder:
 dim=3
 def __init__(self):self.calls=[]
 def embed_passages(self,texts):
  self.calls.append(list(texts));out=[]
  for text in texts:
   data=text.encode();v=np.array([sum(data)%31+1,len(data)%23+1,sum((i+1)*b for i,b in enumerate(data))%19+1],dtype=np.float32);out.append(v/np.linalg.norm(v))
  return out
sources=json.loads(pathlib.Path(request['source']).read_bytes())['passages'];chosen=[];languages=set()
for row in sources:
 if row['input']['language']not in languages and row['input']['language']!='text'and row['result']:
  chosen.append((row['input']['path'],bytes.fromhex(row['input']['source_hex'])));languages.add(row['input']['language'])
plain=[('README.md',b'# IndexProject\n\nInstall a cache.\n# Usage\nRead a value.\n'),('docs/guide.rst',b'# Guide\nA cache in memory.\n'),('deep/docs/README.md',b'# Nested ignored intent\n'),('settings.json',b'{\n"cache": true,\n"text": "\\u00f1"\n}\n'),('project.toml',b'# heading\n[tool.cache]\nsize=3\n'),('input.unknown','plain unicode ni\u00f1o\r\nsecond\n'.encode()),('NOTES.txt',b'<!-- hidden -->\n// hidden\n# text\n'),('broken.txt',b'\xffa\xc3b\xe2\x82c'),('LONG.md',('\n'.join('# Part '+str(i)+'\n'+'x'*1500 for i in range(12))).encode()),('LONG.txt',('x'*5000+'\nignored').encode()),('.hidden.txt',b' # ## \n'),('empty.txt',b'')]
chosen+=plain
cases=[]
def rows(conn):
 tables={}
 for table,order in [('ci_files','id'),('ci_symbols','id'),('ci_imports','id'),('ci_intent_sources','id'),('ci_name_tokens','kind,token,row_id'),('ci_passages','id'),('ci_passage_terms','passage_id,field,term'),('ci_passage_lengths','passage_id,field'),('ci_retrieval_files','file_id'),('meta','key')]:
  tables[table]=[[{'blob_hex':v.hex()}if isinstance(v,bytes)else v for v in row]for row in conn.execute('SELECT * FROM '+table+' ORDER BY '+order)]
 return tables
for rel,source in chosen:
 folder=pathlib.Path(tempfile.mkdtemp(dir=request['scratch']));path=folder/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source)
 import os
 os.utime(path,ns=(1234567890000000000,1234567890000000000))
 conn=connect(folder/'index.db');init_schema(conn);encoder=Encoder();stats=ix.IndexStats();events=[]
 pending=ix._prepare_chunk(conn,folder,[pathlib.Path(rel)],1024*1024,encoder,stats,events,None,{'index','project'})
 if not pending:raise ValueError('original preparation skipped '+rel)
 item=pending[0];texts=list(item.texts);destinations=[list(s)for s in item.slots]
 data=dict(path=rel,source_hex=source.hex(),language=item.language,parsed=dataclasses.asdict(item.parsed)if item.parsed else None,content_hash_hex=item.content_hash.hex(),mtime_ns=item.mtime_ns,source_hash=item.source_sha256,passages=[dataclasses.asdict(p)for p in item.passages],intent_texts=item.intent_texts or [],documents=[dict(target=target,text=text)for target,text in zip(destinations,texts)],extra_stopwords=['index','project'])
 ix._embed_pending(pending,encoder,None);steps=[]
 for action in ('publish','repeat','rebuild','delete'):
  if action in ('publish','repeat'):(ix._write_plain if item.language is None else ix._write_parsed)(conn,item,None)
  elif action=='rebuild':ix.rebuild_name_tokens(conn,pathlib.Path('IndexProject'))
  else:ix.delete_file(conn,rel)
  steps.append(dict(action=action,tables=rows(conn)))
 key=hashlib.sha256(json.dumps(data,ensure_ascii=True,separators=(',',':')).encode()).hexdigest();cases.append(dict(id=key,input=data,encoder_calls=encoder.calls,steps=steps));conn.close();shutil.rmtree(folder)
intents=[]
for rel in ('script.sh','SETTINGS.JSON','a/b/long.yml','a/one.yaml','weird.bin','.config.json'):
 for text in ('#!/bin/sh\n# comment\n// skip\n<!-- skip -->\n# value\n[\n]\n{\n}\nend\n','\u1c89\u200b\x1c','é'*4100):
  source=text.encode();intents.append(dict(path=rel,source_hex=source.hex(),result=ix._plain_text_intents(rel,source)))
value=dict(format='ken-index-publication-reference/1',cases=cases,intents=intents,runtime=dict(system=platform.system(),python=platform.python_version()),source_sha256=hashlib.sha256(pathlib.Path(request['source']).read_bytes()).hexdigest())
pathlib.Path(request['result']).write_text(json.dumps(value,ensure_ascii=True)+'\n')
'''
def capture_publication_reference(reference:Reference,out:Path,source:Path,repo:Path)->dict:
    target=out/'publication-reference.json'
    if target.exists():return json.loads(target.read_bytes())
    out.mkdir(parents=True,exist_ok=True);scratch=out/'publication-scratch';scratch.mkdir(exist_ok=True)
    sdk=repo/('.ken/rust-migration/m3-parsers/sdk-macos'if sys.platform=='darwin'else'.ken/rust-migration/m3-parsers/sdk-linux')
    request=dict(root=str(reference.root),source=str(source),result=str(target),scratch=str(scratch),grammar_cache=str(sdk))
    (out/'publication-request.json').write_text(json.dumps(request));(out/'publication-capture.py').write_text(PUBLICATION_SCRIPT)
    proc=subprocess.run([str(reference.python),str(out/'publication-capture.py'),str(out/'publication-request.json')],cwd=reference.root,env=reference_env(reference,out/'environment'),capture_output=True)
    (out/'publication-stdout').write_bytes(proc.stdout);(out/'publication-stderr').write_bytes(proc.stderr)
    if proc.returncode:raise ValueError(proc.stderr.decode(errors='replace')[-3000:])
    value=json.loads(target.read_bytes());value.update(script_sha256=hashlib.sha256(PUBLICATION_SCRIPT.encode()).hexdigest(),execution=dict(exit=proc.returncode,stdout_sha256=hashlib.sha256(proc.stdout).hexdigest(),stderr_sha256=hashlib.sha256(proc.stderr).hexdigest()));target.write_bytes((json.dumps(value,ensure_ascii=False)+'\n').encode('utf-8',errors='backslashreplace'));return value
