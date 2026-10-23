from pathlib import Path
import hashlib,json,shutil
from tools.rust_migration.source_validate import source_identity
from tools.rust_migration.source_evidence import aggregate_source_matrix

root=Path.cwd();ws=root/'.superpowers/sdd/2026-10-23-rust-source-discovery'
proof=root/'docs/validation/rust-migration-2026-10-23/m3-source-discovery'
proof.mkdir(parents=True)
sources=source_identity(root)
for name in sources:
 dest=proof/'native-sources'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,dest)
tool_files=[*sorted((root/'tools/rust_migration').glob('source_*.py')),
 *sorted((root/'tests/rust_migration').glob('test_source_*.py'))]
tool_files += [root/name for name in ['tools/rust_migration/integration_validate.py','tools/rust_migration/receipts.py',
 'tools/rust_migration/reference.py','tools/rust_migration/fastembed_process.py']]
tooling={}
for path in tool_files:
 name=str(path.relative_to(root));raw=path.read_bytes();tooling[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 dest=proof/'validation-sources'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
(proof/'originals').mkdir()
shutil.copy2(root/'crates/ken-core/tests/fixtures/source-discovery/reference.json',proof/'originals/macos.json')
shutil.copy2(ws/'task-1-reference-linux.json',proof/'originals/linux.json')
platforms={}
for system in ['macos','linux']:
 shutil.copytree(ws/system,proof/system)
 cap=json.loads((proof/system/'observations.json').read_bytes());assert cap['sources']==sources
 platforms[system]={'native_sha256':cap['native_sha256']}
 gates=proof/'gates'/system;gates.mkdir(parents=True)
 for source,dest in [(f'task-3-core-{system}.log','rust-tests.log'),(f'task-3-list-{system}.log','rust-list.log'),
   (f'task-3-build-{system}.log','build.log'),(f'task-3-python-{system}.xml','python.xml'),
   (f'task-3-python-{system}.log','python.log'),(f'task-3-python-list-{system}.log','python-list.log'),
   (f'task-3-clippy-{system}.log','clippy.log'),(f'task-3-fmt-{system}.log','fmt.log')]:shutil.copy2(ws/source,gates/dest)
index=dict(format='ken-source-discovery-matrix/1',sources=sources,tooling=tooling,platforms=platforms,
 predecessor={'path':'docs/validation/rust-migration-2026-10-23/m2-integration-review',
 'manifest_sha256':'293f1de6f3865a8f5c6c4ab489e804b77adaa18863599ef0d044741594ee76bb'})
(proof/'INDEX.json').write_text(json.dumps(index,indent=2)+'\n')
rows=[{'path':str(p.relative_to(proof)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 for p in sorted(proof.rglob('*'))if p.is_file()and p.name!='FILES.json']
(proof/'FILES.json').write_text(json.dumps({'format':'ken-proof-files/1','files':rows},indent=2)+'\n')
result=aggregate_source_matrix(proof,root);assert result['passed'],result
print(json.dumps(result));(ws/'task-3-matrix.json').write_text(json.dumps(result,indent=2)+'\n')
