"""Archive owned typed-piece work and closed controls, without duplicate traces."""
from pathlib import Path
import gzip
import hashlib
import json

root=Path.cwd();out=root/'output/checkpoints/piece-ranking-v126';out.mkdir(exist_ok=False)
base=root/'output/frozen/ranking-diagnostics-owned-v120'
base_manifest=json.loads((base/'SOURCE-MANIFEST.json').read_text())
files={Path(__file__).resolve()}
for version in ('requested-piece-kind-v122b','whole-piece-ranking-v123',
                'whole-piece-control-v124','whole-piece-scope-v125','piece-path-identity-v126'):
    folder=root/'output/frozen'/version
    manifest=json.loads((folder/'SOURCE-MANIFEST.json').read_text())
    files.add(folder/'SOURCE-MANIFEST.json')
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
        if base_manifest['files'].get(name)!=digest:files.add(folder/name)
for version in ('whole-piece-features-v123','whole-piece-ranking-control-v124',
                'whole-piece-scope-control-v125','piece-path-identity-control-v126'):
    folder=root/'output/development'/version
    assert folder.is_dir()
    files.update(p for p in folder.rglob('*') if p.is_file() and p.suffix in {'.json','.jsonl','.npy','.npz','.log'})
kind=root/'output/development/requested-piece-kind-v122b'
files.add(kind/'registration.json')
files.update(kind.glob('*/performance.json'))
files.add(root/'output/development/requested-piece-kind-report-v122b/summary.json')
archive={'scope':'Owned overlays relative to clean v120 plus ALL200 typed-piece features, repo-excluded models and controls. No private acceptance, foreign changes, model download binaries or duplicate431MB native traces.',
    'base_source_receipt':hashlib.sha256((base/'SOURCE-MANIFEST.json').read_bytes()).hexdigest(),
    'files':[]}
for p in sorted(files):
    data=p.read_bytes();digest=hashlib.sha256(data).hexdigest();name=digest+'.gz'
    packed=out/name
    if not packed.exists():packed.write_bytes(gzip.compress(data,compresslevel=6,mtime=0))
    assert hashlib.sha256(gzip.decompress(packed.read_bytes())).hexdigest()==digest
    archive['files'].append({'path':str(p.relative_to(root)),'archive':name,'bytes':len(data),'uncompressed_sha256':digest})
(out/'MANIFEST.json').write_text(json.dumps(archive,indent=2))
summary={'archived_files':len(files),'distinct_gzip_files':len(list(out.glob('*.gz'))),
    'compressed_bytes':sum(p.stat().st_size for p in out.glob('*.gz')),
    'manifest_sha256':hashlib.sha256((out/'MANIFEST.json').read_bytes()).hexdigest(),
    'all_decompressed_payloads_hash_verified':True}
(out/'VERIFIED.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary))
