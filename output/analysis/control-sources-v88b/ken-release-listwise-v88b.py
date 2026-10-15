import hashlib,json,sys
from pathlib import Path
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');E=R/'output/frozen/cpu-listwise-linear-v88b';sys.path.insert(0,str(E/'src'))
from ken.bench.source_receipts import verify_frozen_source
sha=lambda p:hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
O=R/'output/analysis/listwise-linear-ranking-v88b';p=O/'registration.json';r=json.loads(p.read_text());review=R/'output/analysis/listwise-linear-v88b-prefit-review.json'
assert verify_frozen_source(E)==r['engine_receipt']=='ba6e660786f6627fd0af8b31d10a63b714255abb27f411f5cbd95e460ed87387'
assert sha('/private/tmp/ken-listwise-linear-ranking-v88b.py')==r['script_sha256']=='5ffb5c5df97f61a50cad46af9e850ada4ef72d8a7b3d122e5233f8004562c50b'
assert sha(p)=='b2f8b98ed3f4e49f1a3a6009976b80bffc93bf99fb60a5479e7191cdc898bd70'
assert r['pre_fit_ready']and not r['folds']and not r['results']and not list(O.glob('*-linear.json'))
for key in ('inputs','source_bindings','parent_bindings'):
 assert all(sha(path)==digest for path,digest in r[key].items()),key
assert len(r['normalizers'])==16 and all(sha(O/(repo+'-normalizer.npz'))==v['sha256']for repo,v in r['normalizers'].items())
assert not (O/'PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert not (R/'output/analysis/listwise-linear-ranking-v88/PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert review.is_file()
a={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p),'independent_review':str(review),'independent_review_sha256':sha(review),'scope':'Root accepts independently reviewed88b pre-fit artifacts only. Original400/16 whole-repository exclusions/objective/acceptance unchanged.'}
(O/'PRE-FIT-REVIEW-ACCEPTED.json').write_text(json.dumps(a,indent=2));print(json.dumps(a,indent=2))
