from pathlib import Path
import json,hashlib,shutil
from tools.rust_migration.integration_validate import aggregate_integration
repo=Path.cwd();ws=repo/'.superpowers/sdd/2026-10-21-rust-model-integration';source=repo/'docs/validation/rust-migration-2026-10-21/m2-integration';root=ws/'matrix-controls'
shutil.copytree(source,root)
assert aggregate_integration(root,repo)['passed']
profile='linux/transformers/profiles/00/';roles='linux/roles/';cases=[]
def structured(name,path,mutate):cases.append((name,path,mutate,True))
def plain(name,path,mutate):cases.append((name,path,mutate,False))
structured('missing-family',profile+'stdout.json',lambda d:d['selection'].pop('family'))
structured('missing-role',profile+'stdout.json',lambda d:d['selection'].pop('role'))
structured('wrong-profile-revision',profile+'stdout.json',lambda d:d['selection']['spec'].__setitem__('revision','f'*40))
structured('wrong-runtime-version',profile+'inputs.json',lambda d:d['selection']['legacy']['backends']['sentence-transformers'][1].__setitem__(1,'2.8.0'))
structured('changed-native-module',profile+'stdout.json',lambda d:d['rows'][0]['preparation']['trace']['runtime']['module'].__setitem__('sha256','e'*64))
structured('changed-production-source','INDEX.json',lambda d:next(iter(d['workspace_files'].values())).__setitem__('sha256','d'*64))
structured('wrong-compatible-key',profile+'stdout.json',lambda d:d.__setitem__('compatible_key','unrelated'))
structured('changed-vector',profile+'stdout.json',lambda d:d['rows'][0]['result']['vectors'][0].__setitem__(0,1.))
structured('partial-vectors',profile+'stdout.json',lambda d:d['rows'][0]['result']['vectors'].pop())
plain('offline-connect',roles+'fastembed-offline/exec.trace',lambda b:b+b'\nconnect(4, {}, 16) = 0\n')
plain('extra-execveat',profile+'exec.trace',lambda b:b+b'\nexecveat(3, "python", [], [], 0) = 0\n')
structured('false-exec-audit-command',profile+'observed.receipt.json',lambda d:d.__setitem__('command',[v.replace('trace=execve,execveat,connect','trace=execve')for v in d['command']]))
structured('missing-storage-base','INDEX.json',lambda d:d['predecessors'].pop('docs/validation/rust-migration-2026-10-20/m2-transformer-acceptance'))
structured('missing-core-review','INDEX.json',lambda d:d['predecessors'].pop('docs/validation/rust-migration-2026-10-20/m2-transformer-review'))
structured('missing-storage-recovery','linux/gates/storage-recovery/summary.json',lambda d:d['cases'].pop())
plain('passing-flag-instead-of-tests','linux/gates/rust-tests.log',lambda b:b'{"passed":true}\n')
structured('insufficient-capacity','linux/gates/capacity.json',lambda d:d.__setitem__('free_bytes',1))
rows=[];manifest_path=root/'FILES.json';baseline_manifest=manifest_path.read_bytes()
for name,path,change,is_json in cases:
    target=root/path;original=target.read_bytes()
    try:
        if is_json:
            data=json.loads(original);change(data);raw=(json.dumps(data,indent=2)+'\n').encode()
        else:raw=change(original)
        target.write_bytes(raw)
        manifest=json.loads(baseline_manifest)
        entry=next(r for r in manifest['files']if r['path']==path);entry.update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        result=aggregate_integration(root,repo);assert not result['passed']and not result['M2_accepted'],name
        rows.append({'control':name,'rejected':True,'errors':result['errors']});print(json.dumps(rows[-1]),flush=True)
    finally:target.write_bytes(original);manifest_path.write_bytes(baseline_manifest)
assert aggregate_integration(root,repo)['passed']
(ws/'task-5-controls.json').write_text(json.dumps({'controls':rows,'all_rejected':True},indent=2)+'\n')
shutil.rmtree(root)
