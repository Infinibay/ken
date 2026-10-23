"""Assemble raw final evidence without rerunning completed observations."""
from pathlib import Path
import json,hashlib,shutil
from tools.rust_migration.integration_validate import (
    PREDECESSORS,workspace_identity,tooling_identity,compose_python_junit,supplemental_case_ids)
from tools.rust_migration.transformer_evidence import source_identity
repo=Path.cwd();ws=repo/'.superpowers/sdd/2026-10-21-rust-model-integration';proof=repo/'docs/validation/rust-migration-2026-10-21/m2-integration'
proof.mkdir(parents=True,exist_ok=True)
frozen=json.loads((ws/'task-5-final-candidate.json').read_bytes());assert frozen['workspace_files']==workspace_identity(repo)
model_source=json.loads((ws/'task-5-native-source.json').read_bytes());assert model_source==source_identity(repo)
current=tooling_identity(repo);changed={k for k in current.keys()|frozen['tooling'].keys()if current.get(k)!=frozen['tooling'].get(k)}
assert changed=={'tools/rust_migration/integration_validate.py','tools/rust_migration/integration_replay.py','tests/rust_migration/test_integration_gates.py','tests/rust_migration/test_integration_process.py'},changed
for system in ['macos','linux']:
    root=proof/system;root.mkdir(exist_ok=True)
    transform=ws/('factory-transformers-macos'if system=='macos'else'linux-captures/factory-transformers-linux')
    roles=ws/('factory-roles-macos'if system=='macos'else'linux-captures/factory-roles-linux')
    sha=json.loads((transform/'profiles/00/observed.receipt.json').read_bytes())['native_sha256']
    build={'native_sha256':sha,'source_files':model_source}
    (root/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
    for kind,source in [('transformers',transform),('roles',roles)]:
        destination=root/kind;destination.mkdir(exist_ok=True)
        folders=list((source/'profiles').iterdir())if kind=='transformers'else[p for p in source.iterdir()if p.is_dir()and p.name!='cache']
        for folder in folders:
            if not folder.is_dir():continue
            target=destination/('profiles/'+folder.name if kind=='transformers'else folder.name)
            target.mkdir(parents=True,exist_ok=True)
            for file in folder.iterdir():
                if file.is_file()and file.name!='BUILD.json':shutil.copyfile(file,target/file.name)
            receipt=json.loads((target/'observed.receipt.json').read_bytes());assert receipt['native_sha256']==sha
            (target/'BUILD.json').write_text(json.dumps(build,indent=2)+'\n')
    gates=root/'gates';gates.mkdir(exist_ok=True)
    names={'rust-list.log':f'task-5-rust-list-{system}.log','rust-tests.log':f'task-5-final-rust-{system}.log',
        'python-full.log':f'task-5-python-full-{system}.log','clippy.log':f'task-5-final-clippy-{system}.log',
        'fmt.log':f'task-5-final-fmt-{system}.log','toolchain.log':f'task-5-toolchain-{system}.log',
        'python-full-initial.xml':f'task-5-python-full-{system}.xml','python-supplement.xml':f'python-supplement-{system}.xml',
        'build.log':f'task-5-final-build-{system}.log','python-supplement.log':f'task-5-supplement-{system}.log',
        'capacity.json':f'task-5-capacity-{system}.json'}
    for name,source in names.items():shutil.copyfile(ws/source,gates/name)
    compose_python_junit(gates/'python-full-initial.xml',gates/'python-supplement.xml',gates/'python-full.xml',supplemental_case_ids(repo))
    (gates/'initial-tooling.json').write_text(json.dumps(frozen,indent=2)+'\n')
    recovery=ws/('final-recovery-macos'if system=='macos'else'final-recovery-linux')
    shutil.copytree(recovery,gates/'storage-recovery',dirs_exist_ok=True)
    commands={'invocations':{'rust':['cargo','test','--offline','--locked','--workspace','--all-targets'],
        'python':['python','-m','pytest'],'python_supplement':['python','-m','pytest','tests/rust_migration/test_integration_gates.py','tests/rust_migration/test_integration_process.py'],
        'fmt':['cargo','fmt','--all','--','--check'],'clippy':['cargo','clippy','--offline','--locked','--workspace','--all-targets','--','-D','warnings']},
        'exits':json.loads((ws/f'task-5-exits-{system}.json').read_bytes())}
    (gates/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
index={'format':'ken-model-integration-acceptance/1','source_files':model_source,'workspace_files':workspace_identity(repo),
       'tooling':current,'predecessors':PREDECESSORS,'platforms':{'macos':{'profiles':24},'linux':{'profiles':9}}}
(proof/'INDEX.json').write_text(json.dumps(index,indent=2)+'\n')
(proof/'CONTROLLER.py').write_bytes(Path(__file__).read_bytes())
shutil.copytree(ws/'initial-tooling-sources',proof/'initial-tooling-sources',dirs_exist_ok=True)
# The final manifest also authenticates diagnostics and the later review archive.
files=[]
for p in sorted(proof.rglob('*')):
    if p.is_file()and p.name!='FILES.json':
        raw=p.read_bytes();files.append({'path':str(p.relative_to(proof)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
(proof/'FILES.json').write_text(json.dumps({'format':'ken-model-integration-artifacts/1','files':files},indent=2)+'\n')
print('Saved',len(files),'immutable evidence files; acceptance requires independent replay.')
