"""Prepare all fixed lexical source projections before96 public query features."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import time

import ken
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from ken.bench.source_receipts import verify_frozen_source
from lexical_context_catalog import load_context_catalog
from lexical_context_features import FIELDS,FEATURES,context_texts


def sha(path):
 with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


parser=argparse.ArgumentParser()
parser.add_argument('--engine-receipt',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();receipt=verify_frozen_source(E);assert receipt==args.engine_receipt
C=R/'output/analysis/lexical-source-v95';P=R/'output/analysis/c-source-reindex-v66c'
assert sha(C/'registration.json')=='5c5c1d79ca3d4310b80c3dd4f9f1c5936dbf3cb452be8b69fe4919b953781581'
assert sha(P/'registration.json')=='17ac3c3c26170f8929b2cc1a21fe9a7e036603452929c73a435a07e88628dd6a'
roots_path=E/'experiments/search-engine/datasets/roots-development.json'
roots={k:Path(v)for k,v in json.loads(roots_path.read_text()).items()}
parent=json.loads((P/'registration.json').read_text());catalog_meta=json.loads((C/'registration.json').read_text())
assert len(roots)==16 and set(roots)==set(parent['source_repos'])==set(catalog_meta['repos'])
O=args.output;O.mkdir(exist_ok=False)
inputs={str(p):sha(p)for p in(C/'registration.json',P/'registration.json',roots_path,E/'experiments/search-engine/cpu-lexical-source-signals-v96.md')}
manifest={'scope':'ALL16 fixed lexical source fields for every authenticated95context before96queries/labels; no encoding, fit or quality','engine_receipt':receipt,'source95_receipt':'13fec1b8eaf9e6d017d72d61c7ddaee61af83a9a9d8776be34354918b5734556','source_catalog_root':str(C),'source_catalog_registration_sha256':sha(C/'registration.json'),'script_sha256':sha(__file__),'fields':FIELDS,'new_features':FEATURES,'inputs':inputs,'repos':{}}
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
for repo,root in sorted(roots.items()):
 started=time.perf_counter();metadata=parent['source_repos'][repo]
 assert all(sha(root/path)==digest for path,digest in metadata['file_hashes'].items())
 catalog=load_context_catalog(folder=C,registration_sha256=manifest['source_catalog_registration_sha256'],engine_receipt=manifest['source95_receipt'],repo=repo,index=P/'indices'/(repo+'.db'))
 inputs.update(catalog.receipts)
 destination=O/(repo+'.db');db=sqlite3.connect(destination)
 db.execute('CREATE TABLE projections(entity TEXT PRIMARY KEY,source_hash TEXT,generation TEXT,full TEXT,nested TEXT,full_sha256 TEXT,nested_sha256 TEXT)')
 nested_bytes=0
 for entity,context in sorted(catalog.contexts.items(),key=lambda item:(item[0].path,item[0].kind,item[0].qualname or '',item[0].owner or '',item[0].definition_ordinal)):
  fields=context_texts(context);assert tuple(fields)==FIELDS
  identity=json.dumps({'path':entity.path,**entity.to_dict()},sort_keys=True,separators=(',',':'))
  full=fields['lexical_full'];nested=fields['lexical_nested'];nested_bytes+=len(nested.encode())
  db.execute('INSERT INTO projections VALUES (?,?,?,?,?,?,?)',(identity,context.source_hash,context.generation,full,nested,hashlib.sha256(full.encode()).hexdigest(),hashlib.sha256(nested.encode()).hexdigest()))
 db.commit();count=db.execute('SELECT count(*) FROM projections').fetchone()[0];db.close()
 assert count==len(catalog.contexts)==catalog_meta['repos'][repo]['counts']['contexts']
 assert all(sha(root/path)==digest for path,digest in metadata['file_hashes'].items())
 manifest['repos'][repo]={'contexts':count,'database_sha256':sha(destination),'source_generation':catalog.source_generation,'generation_id':catalog.generation_id,'source_index_sha256':metadata['new_source_index_sha256'],'nested_projected_bytes':nested_bytes,'ms':(time.perf_counter()-started)*1000}
 (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'source_projection_ready':repo,**manifest['repos'][repo]}),flush=True)
 del catalog,context,fields;gc.collect()
assert len(manifest['repos'])==16 and sum(v['contexts']for v in manifest['repos'].values())==36194
assert all(sha(path)==digest for path,digest in inputs.items())and verify_frozen_source(E)==receipt
assert not any(name in sys.modules for name in('torch','transformers','onnxruntime','lightgbm'))
manifest.update(complete=True,peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
