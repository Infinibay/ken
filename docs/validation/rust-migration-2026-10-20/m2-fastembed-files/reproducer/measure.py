from pathlib import Path
import hashlib,json,subprocess,tempfile,tomllib
from tools.rust_migration.fastembed_reference import source_state
root=Path.cwd();private=root/'.ken/rust-migration/m2-fastembed';probe=private/'file-copy-measurement';binary=root/'.ken/rust-migration/m2-translation/source-t4a/target/release/ken-model-file-measurement'
root_packages={(x['name'],x['version'],x.get('source'),x.get('checksum')) for x in tomllib.loads((root/'Cargo.lock').read_text())['package']}
packages=tomllib.loads((probe/'Cargo.lock').read_text())['package'];assert all((x['name'],x['version'],x.get('source'),x.get('checksum')) in root_packages or x['name']=='ken-model-file-measurement' for x in packages)
models=json.loads((root/'crates/ken-models/resources/fastembed-catalog.json').read_bytes())['models']
out=private/'file-copy-results-current';out.mkdir(exist_ok=False);results=[]
for index,model in enumerate(models):
    before=source_state(private/'sources',model)
    definition=out/f'{index:02d}.assets.json';definition.write_text(json.dumps(model['assets'],indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='model-copy-parent-',dir=private) as directory:
        argv=[str(binary),str(definition),before['snapshot'],directory,model['graph']]
        child=subprocess.run(argv,capture_output=True,text=True,timeout=300)
        (out/f'{index:02d}.stderr.log').write_text(child.stderr);(out/f'{index:02d}.stdout.log').write_text(child.stdout)
        assert child.returncode==0,child.stderr
        receipt=json.loads(child.stdout);assert receipt['verified'] and receipt['private_files_removed']
        assert receipt['peak_rss_bytes']<128*1024**2,receipt
        assert source_state(private/'sources',model)==before
        results.append({'model':model['name'],'registered_bytes':sum(r['bytes'] for r in model['assets']['artifacts'].values()),**receipt})
        print(json.dumps({'copied_and_audited':len(results),'model':model['name'],'peak_rss_bytes':receipt['peak_rss_bytes']}),flush=True)
model=next(m for m in models if m['name']=='jinaai/jina-embeddings-v3');invalid=json.loads(json.dumps(model['assets']));invalid['artifacts']['tokenizer_config.json']['sha256']='0'*64
path=out/'invalid-after-large-copy.assets.json';path.write_text(json.dumps(invalid,indent=2)+'\n');before=source_state(private/'sources',model)
with tempfile.TemporaryDirectory(prefix='failed-model-copy-',dir=private) as directory:
    child=subprocess.run([str(binary),str(path),before['snapshot'],directory,model['graph']],capture_output=True,text=True,timeout=300)
    (out/'invalid.stderr.log').write_text(child.stderr);(out/'invalid.stdout.log').write_text(child.stdout)
    assert child.returncode==0,child.stderr
    failure=json.loads(child.stdout);assert not failure['verified'] and failure['private_files_removed']
    assert 'tokenizer_config.json' in failure['error'] and source_state(private/'sources',model)==before
(probe/'provenance.json').write_text(json.dumps({'scope':'private real-file verification/closure measurement, not encoder inference acceptance','binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'root_locked_packages':len(packages)-1,'private_package':'ken-model-file-measurement','root_files':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'crates/ken-models/src/assets.rs',root/'crates/ken-models/src/lib.rs',root/'crates/ken-models/src/file_assets.rs',root/'crates/ken-models/src/verified_file.rs',root/'crates/ken-models/src/onnx_wire.rs',root/'crates/ken-models/src/onnx_dependencies.rs']}},indent=2)+'\n')
summary={'scope':'30 actual file sets copied/audited/dropped with fixed128MiB process RSS cap; no neural inference','models':results,'failure_after_large_copy':failure,'passed':True}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'passed':True,'models':len(results),'bytes':sum(r['registered_bytes'] for r in results),'max_rss_bytes':max(r['peak_rss_bytes'] for r in results),'failed_large_copy_cleaned':True}),flush=True)
