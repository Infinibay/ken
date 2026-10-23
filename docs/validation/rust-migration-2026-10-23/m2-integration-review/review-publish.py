from pathlib import Path
import hashlib,json,shutil,subprocess
from tools.rust_migration.integration_validate import workspace_identity,tooling_identity

root=Path.cwd();ws=root/'.superpowers/sdd/2026-10-21-rust-model-integration'
proof=root/'docs/validation/rust-migration-2026-10-23/m2-integration-review'
base=root/'.ken/rust-migration/m2-integration/source-6eca4cb1'
with(ws/'progress.md').open('a')as out:
 out.write('Final: fixed crossed judge runtime backend — cold_judge_rejects_crossed_runtime_declarations RED→GREEN (both directions onmacOS, Torch-in-MLX onLinux; an MLX declaration itself requiresmacOS), wholeRust318/318macOS and308/308Linux.\nFinal: fixed actual destination/incremental disk capacity —3capacityAPI cases and actual ready-cache bypass RED→GREEN;7source/capacity cases, wholeRust318/318and308/308. Per-filesystem sums use actual device/free space and one3GiBreserve; cached/borrowed source bytes are not reallocated.\nFinal: fixed FastEmbed actual preparation binding —24role mutations RED→GREEN, exact old whole-matrix false acceptance reproduced,6resealed whole-matrix mutations reject, restored matrix passes. AffectedPython77/77eachplatform.\nFinal review clean after the single verified repair pass; no minors from this review; prior recorded minors remain historical. Current wholeRustworkspace suites andclippy bothplatforms pass; original1066guard passes. FulloriginalPython/neural histories remain at their authenticated unchanged source identities. ContinueM3without merge/push or confirmation.\n')
shutil.copy2(ws/'progress.md',proof/'LEDGER.md')
(proof/'RULINGS.md').write_text('# Rulings I made\n\n'+'\n'.join(line for line in (ws/'progress.md').read_text().splitlines()if 'Ruling:'in line)+'\n\n# Deferred minors\n\nNone in this integration review; earlier independent blocks retain their own deferred findings.\n')
for file in ws.glob('review-*'):
 if file.is_file()and file.suffix in ('.log','.json','.xml','.py'):shutil.copy2(file,proof/file.name)
modified=['crates/ken-models/src/artifact_cache.rs','crates/ken-models/src/model_factory.rs','crates/ken-models/src/model_sources.rs','crates/ken-models/tests/model_factory.rs','tools/rust_migration/integration_replay.py','tests/rust_migration/test_integration_role_replay.py']
for name in modified:
 for label,source in [('source-before',base),('source-after',root)]:
  dest=proof/label/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dest)
patch=subprocess.run(['git','diff','6eca4cb1','--',*modified],capture_output=True,check=True).stdout
(proof/'REPAIR.patch').write_bytes(patch)
identity=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
prior=root/'docs/validation/rust-migration-2026-10-21/m2-integration'
index=dict(format='ken-model-integration-review/1',base_commit='6eca4cb12752a342cee2dc4df2c9c4fc879424a1',
 base_manifest_sha256=identity(prior/'FILES.json'),base_workspace=json.loads((prior/'INDEX.json').read_bytes())['workspace_files'],
 current_workspace=workspace_identity(root),current_tooling=tooling_identity(root),modified_files=modified,
 gates=json.loads((ws/'review-gates.json').read_bytes()),controls=json.loads((ws/'review-controls.json').read_bytes()),
 originals=json.loads((ws/'review-originals.json').read_bytes()),M2_accepted=True,M3_accepted=False)
changes=[p for p in index['base_workspace'].keys()|index['current_workspace'].keys()if index['base_workspace'].get(p)!=index['current_workspace'].get(p)]
assert set(changes)==set(modified[:3]),changes
for system in ['macos','linux']:
 assert index['gates'][system]['rust_cases']==(318 if system=='macos' else 308)
(proof/'INDEX.json').write_text(json.dumps(index,indent=2)+'\n')
print('Archived review, full ledger/rulings,3source-only production repairs and actual current regression logs; originals intact.')
