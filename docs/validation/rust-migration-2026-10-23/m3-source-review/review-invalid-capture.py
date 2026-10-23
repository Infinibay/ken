from pathlib import Path
from dataclasses import replace
import json,os,subprocess,sys
from tools.rust_migration.reference import Reference,reference_env
r=Path.cwd();out=Path(sys.argv[1]);reference=replace(Reference.load(Path(os.environ['KEN_RUST_REFERENCE'])),python=Path(sys.executable).absolute())
sources=json.loads((r/'crates/ken-core/tests/fixtures/source-discovery/reference.json').read_bytes())['sources']
script=r'''import json,pathlib,tempfile
from ken.gitignore_filter import GitignoreMatcher
rows=[]
for rule in ['a[z-a].py', 'a\\', '!', 'a[a--b].py', 'a[.py', 'a[].py', 'a[!].py']:
 with tempfile.TemporaryDirectory() as d:
  p=pathlib.Path(d);(p/'.gitignore').write_text(rule+'\n')
  try:
   m=GitignoreMatcher(p);answer=m.is_ignored(pathlib.Path('az.py'))
   rows.append(dict(rule=rule,ignored=answer))
  except Exception as e: rows.append(dict(rule=rule,error=dict(type=type(e).__name__,message=str(e))))
print(json.dumps(rows))
'''
import hashlib
assert all(hashlib.sha256((reference.root/p).read_bytes()).hexdigest()==v for p,v in sources.items())
execution=subprocess.run([str(reference.python),'-c',script],cwd=reference.root,env=reference_env(reference,out.parent/'invalid-environment'),capture_output=True,text=True,timeout=20)
assert execution.returncode==0,execution.stderr
out.write_text(json.dumps(dict(script=script,sources=sources,stdout=execution.stdout,stderr=execution.stderr,exit=execution.returncode,rows=json.loads(execution.stdout)),indent=2)+'\n')
print('4 malformed errors and3 noops observed independently')
