from pathlib import Path
import hashlib,json,shutil
from tools.rust_migration.source_evidence import aggregate_source_matrix
root=Path.cwd();ws=root/'.superpowers/sdd/2026-10-23-rust-source-discovery'
proof=root/'docs/validation/rust-migration-2026-10-23/m3-source-discovery';target=ws/'matrix-controls'
shutil.copytree(proof,target);assert aggregate_source_matrix(target,root)['passed']
prefix='macos/observations/glob/00/';linux='linux/observations/glob/00/'
cases=[('membership',prefix+'stdout.json',lambda d:d['entries'][-1].__setitem__('path','wrong.py')),
 ('directory',prefix+'stdout.json',lambda d:d['entries'][0].__setitem__('is_dir',not d['entries'][0]['is_dir'])),
 ('ordering',prefix+'stdout.json',lambda d:d['entries'].reverse()),
 ('source','INDEX.json',lambda d:next(iter(d['sources'].values())).__setitem__('sha256','f'*64)),
 ('missing-case','macos/observations.json',lambda d:d['observations'].pop()),
 ('rules','originals/macos.json',lambda d:d['definitions'][0]['files'].__setitem__('.gitignore','*\n')),
 ('integrity','macos/integrity/stdout.json',lambda d:d['errors'].clear()),
 ('false-audit-command',linux+'execution.json',lambda d:d.__setitem__('command',[x.replace('trace=execve,execveat,connect','trace=execve')for x in d['command']]))]
cases += [('extra-execveat',linux+'exec.trace',lambda b:b+b'\nexecveat(3,"python",[],[],0)=0\n'),
 ('passing-flag-instead-of-tests','linux/gates/rust-tests.log',lambda b:b'{"passed":true}\n')]
# Actual gate layout is gates/<platform>, independently of native captures.
cases[-1]=(cases[-1][0],'gates/linux/rust-tests.log',cases[-1][2])
manifest=target/'FILES.json';original_manifest=manifest.read_bytes();rows=[]
for name,path,change in cases:
 file=target/path;original=file.read_bytes()
 try:
  if path.endswith('.json'):
   data=json.loads(original);change(data);raw=(json.dumps(data)+'\n').encode()
  else:raw=change(original)
  file.write_bytes(raw);contents=json.loads(original_manifest)
  entry=next(e for e in contents['files']if e['path']==path);entry.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
  manifest.write_text(json.dumps(contents)+'\n');result=aggregate_source_matrix(target,root)
  assert not result['passed']and not result['M3a_accepted'],name
  rows.append(dict(control=name,rejected=True,errors=result['errors']))
 finally:file.write_bytes(original);manifest.write_bytes(original_manifest)
assert aggregate_source_matrix(target,root)['passed'];shutil.rmtree(target)
(ws/'task-3-controls.json').write_text(json.dumps(dict(all_rejected=True,controls=rows),indent=2)+'\n')
print('All10resealed actual source-matrix mutations rejected; restored baseline passes.')
