"""Observe frozen parser calls and syntax, independently from all Rust results."""
from __future__ import annotations
from collections import Counter
import hashlib,importlib.metadata,json,os
from pathlib import Path
import subprocess
from .reference import Reference,reference_env

LANGUAGES=('bash','c','cpp','csharp','css','dart','go','graphql','html','java',
 'javascript','kotlin','php','powershell','python','ruby','rust','sql','typescript')
PACKAGES={'tree-sitter':'0.25.2','tree-sitter-language-pack':'1.8.1','tree-sitter-go':'0.25.0',
 'tree-sitter-java':'0.23.5','tree-sitter-javascript':'0.25.0','tree-sitter-python':'0.25.0',
 'tree-sitter-rust':'0.24.2','tree-sitter-typescript':'0.23.2'}
SUITE=['tests/parsers','tests/retrieval/test_language_scopes.py','tests/retrieval/test_scope_documentation.py']
SUPPLEMENTS={
 'bash':('inline.sh',b'# Read a value\nread_value() { echo value; }\n'),
 'c':('inline.c',b'/* Read a value. */\nint read_value(void) { return 1; }\n'),
 'cpp':('inline.cpp',b'namespace sample { struct Reader { int read() { return 1; } }; }\n'),
 'csharp':('inline.cs',b'namespace Sample { class Reader { public int Read() { return 1; } } }\n'),
 'css':('inline.css',b'/* Read style */\n.reader { --color: red; color: var(--color); }\n'),
 'dart':('inline.dart',b'/// Read a value.\nclass Reader { int read() => 1; }\n'),
 'go':('inline.go',b'package sample\n// Read a value.\nfunc Read() int { return 1 }\n'),
 'graphql':('inline.graphql',b'"A reader"\ntype Reader { value: Int! }\nquery Read { value }\n'),
 'html':('inline.html',b'<!doctype html>\n<div id="reader"><script src="read.js"></script></div>\n'),
 'java':('Inline.java',b'/** Read a value. */\nclass Reader { int read() { return 1; } }\n'),
 'javascript':('inline.js',b'/** Read a value. */\nexport const read = () => { return 1; };\n'),
 'kotlin':('inline.kt',b'/** Read a value. */\nclass Reader { fun read(): Int { return 1 } }\n'),
 'php':('inline.php',b'<?php\n/** Read a value. */\nfunction read_value() { return 1; }\n'),
 'powershell':('inline.ps1',b'# Read a value\nfunction Read-Value { return 1 }\n'),
 'python':('inline.py',b'"""Read module."""\n@decorate\ndef read_value():\n    """Read a value.\n\n    Complete documentation.\n    """\n    return 1\n'),
 'ruby':('inline.rb',b'# Read a value.\nclass Reader\n  def read\n    1\n  end\nend\n'),
 'rust':('inline.rs',b'//! Module documentation.\n/// Read a value.\n#[inline]\npub fn read_value() -> i32 { 1 }\n'),
 'sql':('inline.sql',b'-- Reader table\nCREATE TABLE readers (id INTEGER PRIMARY KEY);\n'),
 'typescript':('inline.ts',b'/** Read a value. */\nexport interface Reader { read(): number; }\nexport const read = (): number => 1;\n'),
 'tsx':('inline.tsx',b'export const Reader = () => <div id="reader">value</div>;\n'),
}

SCRIPT=r'''
import dataclasses,functools,hashlib,importlib,importlib.metadata,json,pathlib,platform,sys
import pytest
request=json.loads(pathlib.Path(sys.argv[1]).read_bytes()); root=pathlib.Path(request['reference']).resolve()
import tree_sitter_language_pack as pack
pack.configure({'cache_dir':request['grammar_cache']})
import ken.parsers as registry
modules={name:importlib.import_module('ken.parsers.'+name)for name in request['languages']}
for module in [registry,*modules.values()]:
 if not pathlib.Path(module.__file__).resolve().is_relative_to(root): raise ValueError('wrong original module root')
versions={name:importlib.metadata.version(name) for name in request['packages']}
if versions!=request['packages']:raise ValueError('wrong original grammar versions')
observed={};calls=0;active_test=None;discovered=[];test_states=[]

def shape(node):
 rows=[];pending=[(node,None,None)]
 while pending:
  current,parent,field=pending.pop();index=len(rows)
  rows.append([current.type,current.is_named,current.is_missing,current.start_byte,current.end_byte,
    list(current.start_point),list(current.end_point),parent,field,current.has_error])
  children=current.children
  for i in range(len(children)-1,-1,-1):pending.append((children[i],index,current.field_name_for_child(i)))
 return rows

def wrap(name,function):
 @functools.wraps(function)
 def call(source,hint):
  global calls
  calls+=1
  result=function(source,hint)
  grammar='tsx'if name=='typescript'and hint.endswith('.tsx')else name
  identity=hashlib.sha256(name.encode()+b'\0'+hint.encode()+b'\0'+source).hexdigest()
  output=dataclasses.asdict(result)
  if identity in observed:
   if observed[identity]['parsed']!=output: raise ValueError('nondeterministic original parser')
   observed[identity]['calls']+=1
   if active_test and active_test not in observed[identity]['tests']:observed[identity]['tests'].append(active_test)
   return result
  module=modules[name]
  parser=(module._PARSER_TSX if grammar=='tsx'else module._PARSER_TS)if name=='typescript'else module._PARSER
  tree=parser.parse(source)
  observed[identity]=dict(id=identity,input=dict(language=name,hint=hint,source_hex=source.hex()),
    grammar=grammar,parsed=output,syntax=shape(tree.root_node),calls=1,tests=[active_test]if active_test else[])
  return result
 return call

for name,module in modules.items():
 attribute={'javascript':'parse_js_file','typescript':'parse_ts_file'}.get(name,'parse_'+name+'_file')
 original=getattr(module,attribute); wrapped=wrap(name,original);setattr(module,attribute,wrapped)
 if getattr(registry,attribute,None)is original:setattr(registry,attribute,wrapped)
 for extension,(language,function)in list(registry.LANGUAGE_BY_EXT.items()):
  if function is original:registry.LANGUAGE_BY_EXT[extension]=(language,wrapped)

class Plugin:
 def pytest_collection_finish(self,session):discovered.extend(item.nodeid for item in session.items)
 def pytest_runtest_setup(self,item):
  global active_test
  active_test=item.nodeid
 def pytest_runtest_logreport(self,report):
  if report.when=='call'or report.failed or report.skipped:test_states.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome))

exit_code=pytest.main(['-o','addopts=','--rootdir='+str(root),'-q',*request['suite'],
 '--junitxml='+request['junit']],plugins=[Plugin()])
active_test=None
for grammar,example in request['supplements'].items():
 hint=example['hint'];source=bytes.fromhex(example['source_hex']);name='typescript'if grammar=='tsx'else grammar
 attribute={'javascript':'parse_js_file','typescript':'parse_ts_file'}.get(name,'parse_'+name+'_file')
 for sample in [source,b'',source+b'\n\xff\xc3\x00',source[:max(1,len(source)//2)],source+b'\n// caf\xc3\xa9 \xf0\x9f\xa6\x80\n']:
  getattr(modules[name],attribute)(sample,hint)
result=dict(format='ken-parser-reference/1',cases=list(observed.values()),calls=calls,
 runtime=dict(system=platform.system(),machine=platform.machine(),python=platform.python_version(),packages=versions),
 discovered=discovered,test_states=test_states,original_test_exit=exit_code)
pathlib.Path(request['result']).write_text(json.dumps(result,ensure_ascii=True)+'\n')
sys.exit(exit_code)
'''


def parser_owner_hashes(repo:Path)->dict[str,str]:
    baseline=json.loads((repo/'docs/validation/rust-migration-2026-10-18/baseline.json').read_bytes())
    def selected(name):
        return name.startswith(('src/ken/parsers/','tests/parsers/')) or name in SUITE[1:]+['tests/conftest.py']
    return {r['path']:r['sha256'] for r in baseline['files'] if selected(r['path'])}


def validate_parser_reference(result:dict)->list[str]:
    try:
        def require(value,message):
            if not value:raise ValueError(message)
        require(result['format']=='ken-parser-reference/1','wrong reference format')
        require(result['runtime']['packages']==PACKAGES,'original package versions differ')
        require(result['script_sha256']==hashlib.sha256(SCRIPT.encode()).hexdigest(),'original capture script differs')
        cases=result['cases'];require(bool(cases),'empty parser corpus')
        ids=[];coverage=Counter();calls=0
        for case in cases:
            request=case['input'];source=bytes.fromhex(request['source_hex'])
            identity=hashlib.sha256(request['language'].encode()+b'\0'+request['hint'].encode()+b'\0'+source).hexdigest()
            require(case['id']==identity and request['language']in LANGUAGES,'wrong input identity')
            grammar='tsx'if request['language']=='typescript'and request['hint'].endswith('.tsx')else request['language']
            require(case['grammar']==grammar and bool(case['syntax']),'missing original syntax')
            require(set(case['parsed'])=={'symbols','imports','docstring','scopes'},'incomplete original dataclass')
            coverage[grammar]+=1;ids.append(identity);calls+=case['calls']
        require(len(ids)==len(set(ids))and calls==result['calls'],'parser case inventory differs')
        require(set(coverage)==set(SUPPLEMENTS),'missing language or grammar')
        require(result['coverage']=={g:dict(cases=n)for g,n in sorted(coverage.items())},'coverage inventory differs')
        require(result['original_test_exit']==0 and result['test_execution']['exit']==0,'original suite failed')
        require(bool(result['discovered'])and len(result['discovered'])==len(set(result['discovered'])),'test discovery differs')
        require({r['nodeid']for r in result['test_states']}==set(result['discovered'])and
            all(r['when']=='call'and r['outcome']=='passed'for r in result['test_states']),'original test states differ')
        return []
    except (ValueError,KeyError,TypeError)as error:return[str(error)]


def capture_parser_reference(reference:Reference,out:Path,*,repo:Path|None=None)->dict:
    repo=repo or Path.cwd();owners=parser_owner_hashes(repo)
    for name,digest in owners.items():
        path=reference.root/name
        if not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('changed original parser: '+name)
    if (out/'reference.json').exists():
        result=json.loads((out/'reference.json').read_bytes())
        if result['owners']!=owners or validate_parser_reference(result):raise ValueError('stale parser reference')
        return result
    # Configuration points at the already available original SDK modules. Check
    # every borrowed file before the child imports parsers, so it cannot download.
    import tree_sitter_language_pack as pack
    grammar_cache=Path(os.environ.get('KEN_PARSER_ORIGINAL_GRAMMARS',pack.cache_dir()))
    suffix='.dylib'if os.uname().sysname=='Darwin'else'.so'
    for name in set(LANGUAGES)-{'go','java','javascript','python','rust','typescript'}:
        library=grammar_cache/('libtree_sitter_'+('c_sharp'if name=='csharp'else name)+suffix)
        if not library.is_file():raise ValueError('original native grammar unavailable: '+str(library))
    out.mkdir(parents=True,exist_ok=True);out=out.resolve()
    request=dict(reference=str(reference.root),grammar_cache=str(grammar_cache),languages=LANGUAGES,
        packages=PACKAGES,suite=SUITE,junit=str(out/'original-tests.xml'),result=str(out/'original-observations.json'),
        supplements={g:dict(hint=h,source_hex=s.hex())for g,(h,s)in SUPPLEMENTS.items()})
    (out/'request.json').write_text(json.dumps(request,indent=2)+'\n')
    command=[str(reference.python),'-c',SCRIPT,str(out/'request.json')]
    execution=subprocess.run(command,cwd=reference.root,env=reference_env(reference,out/'environment'),
        capture_output=True,timeout=120,check=False)
    (out/'stdout.log').write_bytes(execution.stdout);(out/'stderr.log').write_bytes(execution.stderr)
    if execution.returncode:raise RuntimeError('original parser capture failed: '+execution.stdout[-4000:].decode(errors='replace')+'\n'+execution.stderr[-2000:].decode(errors='replace'))
    raw=(out/'original-observations.json').read_bytes()
    if len(raw)>64*1024*1024:raise ValueError('original parser observations exceed64MiB')
    result=json.loads(raw);coverage=Counter(c['grammar']for c in result['cases'])
    result.update(owners=owners,script_sha256=hashlib.sha256(SCRIPT.encode()).hexdigest(),
        coverage={g:dict(cases=n)for g,n in sorted(coverage.items())},
        test_execution=dict(exit=execution.returncode,python=str(reference.python),cwd=str(reference.root),
            stdout_sha256=hashlib.sha256(execution.stdout).hexdigest(),stderr_sha256=hashlib.sha256(execution.stderr).hexdigest(),
            observations_sha256=hashlib.sha256(raw).hexdigest(),timeout_s=120))
    errors=validate_parser_reference(result)
    if errors:raise ValueError(errors)
    (out/'reference.json').write_text(json.dumps(result,indent=2,ensure_ascii=True)+'\n')
    return result
