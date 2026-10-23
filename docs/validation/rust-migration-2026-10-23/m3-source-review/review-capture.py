from pathlib import Path
import hashlib,json,subprocess,os,sys
from dataclasses import replace
from tools.rust_migration.reference import Reference,reference_env
from tools.rust_migration.source_reference import capture_sources,OWNERS
r=Path.cwd(); w=r/'.superpowers/sdd/2026-10-23-rust-source-discovery'
reference=replace(Reference.load(Path(os.environ.get('KEN_RUST_REFERENCE',str(r/'.ken/rust-migration/m2-optional/reference-final-t9')))),python=Path(sys.executable).absolute())
sources=json.loads((r/'crates/ken-core/tests/fixtures/source-discovery/reference.json').read_bytes())['sources']
cases=[]
patterns=[('braces','a{b,c}.py\n'),('question','a?.py\n'),('negated-class','a[!b].py\n'),('class','a[é-ê].py\n'),('directory-negation','foo/*\n!foo/\n'),('double-star-directory','**/\n'),('special-classes','a[][!].py\na[&~].py\n'),('unclosed','a[.py\n'),('priority','foo/*\n!foo/\nfoo/deep/*.py\n!foo/deep/keep.py\n')]
for name,pattern in patterns:
    for where in ['.gitignore','.kenignore','pkg/.gitignore']:
        prefix='pkg/' if where.startswith('pkg/') else ''
        names=['a{b,c}.py','ab.py','ac.py','aé.py','aê.py','a🦀.py','a[.py','a].py','a!.py','a&.py','a~.py','keep.py','foo/deep/main.py','foo/deep/keep.py']
        files={prefix+n:'' for n in names}; files[where]=pattern
        queries=[dict(path=prefix+n,is_dir=False) for n in names]
        queries += [dict(path=prefix+n,is_dir=True) for n in ['foo','foo/deep']]
        cases.append(dict(id=name+'-'+where.replace('/','-').replace('.',''),files=files,queries=queries,scopes=['.',prefix+'foo',prefix+'foo/deep']))
cases.append(dict(id='scope-under-file',files={'file.py':''},queries=[],scopes=['file.py/child','file.py/child/grandchild']))
result=capture_sources(reference,cases,sources,w/'review-reference-sandbox')
out=r/'crates/ken-core/tests/fixtures/source-discovery/reference-review.json'
out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
# Malformed errors must be observed independently; capture_sources intentionally
# rejects an original process which fails during matcher construction/evaluation.
script="""import json,pathlib,tempfile
from ken.gitignore_filter import GitignoreMatcher
rows=[]
for rule in ['a[z-a].py', 'a\\\\', '!', 'a[.py', 'a[].py', 'a[!].py']:
 with tempfile.TemporaryDirectory() as d:
  p=pathlib.Path(d);(p/'.gitignore').write_text(rule+'\\n')
  try:
   m=GitignoreMatcher(p); answer=m.is_ignored(pathlib.Path('az.py'))
   rows.append(dict(rule=rule,ignored=answer))
  except Exception as e: rows.append(dict(rule=rule,error=dict(type=type(e).__name__,message=str(e))))
print(json.dumps(rows))
"""
execution=subprocess.run([str(reference.python),'-c',script],cwd=reference.root,env=reference_env(reference,w/'review-reference-sandbox'),capture_output=True,text=True,timeout=20)
assert execution.returncode==0,execution.stderr
(w/'review-invalid-original.json').write_text(json.dumps(dict(script=script,sources=sources,stdout=execution.stdout,stderr=execution.stderr,exit=execution.returncode,rows=json.loads(execution.stdout)),indent=2)+'\n')
print(len(cases),'trees',sum(len(c['queries']) for c in cases),'queries',sum(len(c['walks']) for c in result['cases']),'walks')
print(execution.stdout)
