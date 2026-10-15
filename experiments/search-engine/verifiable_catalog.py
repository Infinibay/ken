"""Close an ALL-source canonical identity catalog before reading new questions."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.candidates import owner_passages
from verifiable_pieces import SourceCatalog, canonical
import ken


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--source-metadata',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((a.source_metadata/'manifest.json').read_text())
    for name,record in manifest['files'].items():
        if sha(a.source_metadata/name)!=record['sha256']:raise ValueError('metadata changed')
    roots=json.loads((a.source_metadata/'roots.json').read_text())
    source=a.workspace/'output/analysis/c-source-reindex-v66c'
    reg=json.loads((source/'registration.json').read_text())
    receipt={'role':'ALL8 source-only canonical catalog; no questions or Gold read',
        'source_metadata_sha256':sha(a.source_metadata/'manifest.json'),
        'engine_receipt':verify_frozen_source(Path(ken.__file__).resolve().parents[2]),
        'source_registration_sha256':sha(source/'registration.json'),'repos':{}}
    for repo,root in sorted(roots.items()):
        index=source/'indices'/(repo+'.db')
        if sha(index)!=reg['source_repos'][repo]['new_source_index_sha256']:
            raise ValueError('source index changed: '+repo)
        db=sqlite3.connect(f'file:{index}?mode=ro',uri=True);db.row_factory=sqlite3.Row
        catalog=SourceCatalog(root,owner_passages(db));inventory=catalog.source_inventory()
        path=a.output/(repo+'.jsonl')
        path.write_text(''.join(canonical(row)+'\n' for row in inventory))
        receipt['repos'][repo]={'root':root,'owners':len(inventory),
            'indexed_files':db.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0],
            'inventory_sha256':sha(path),'classes':sum(r['entity']['kind']=='class' for r in inventory)}
        db.close();print(json.dumps({'repo':repo,'owners':len(inventory)}),flush=True)
    (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
