"""Verify complete source preparation before a caller may open public queries."""
import json
from pathlib import Path

from ettin_cpu import sha


def verify_source_preparation(workspace,metadata):
    workspace=Path(workspace);metadata=Path(metadata)
    manifest_path=metadata/'manifest.json';manifest=json.loads(manifest_path.read_text())
    for name,record in manifest['files'].items():
        path=(metadata/name).resolve()
        if not path.is_relative_to(metadata.resolve()) or sha(path)!=record['sha256']:
            raise ValueError('source metadata changed/escaped')
    roots=json.loads((metadata/'roots.json').read_text())
    catalog_dir=workspace/'output/analysis/verifiable-pieces-catalog-v98'
    catalog=json.loads((catalog_dir/'receipt.json').read_text())
    if catalog['source_metadata_sha256']!=sha(manifest_path) or set(catalog['repos'])!=set(roots):
        raise ValueError('ALL-source catalog preparation differs')
    for repo,record in catalog['repos'].items():
        if sha(catalog_dir/(repo+'.jsonl'))!=record['inventory_sha256']:
            raise ValueError('canonical source inventory changed')
    for line in (metadata/'file-hashes-draft.jsonl').read_text().splitlines():
        row=json.loads(line);root=Path(roots[row['repo_id']]).resolve()
        path=(root/row['path']).resolve()
        if not path.is_relative_to(root) or sha(path)!=row['source_hash']:
            raise ValueError('ALL-source snapshot changed')
    from ken.bench.source_receipts import verify_frozen_source
    frozen=workspace/'output/frozen/cpu-rank-consensus-v97b'
    receipt=verify_frozen_source(frozen)
    if receipt!=catalog['engine_receipt']:raise ValueError('prepared engine differs')
    return roots,{'catalog_receipt_sha256':sha(catalog_dir/'receipt.json'),
        'source_metadata_sha256':sha(manifest_path),'engine_receipt':receipt}
