import hashlib,json,sys
from pathlib import Path
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');E=R/'output/frozen/cpu-query-actions-v90';sys.path.insert(0,str(E/'src'))
from ken.bench.source_receipts import verify_frozen_source
sha=lambda p:hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
O=R/'output/analysis/query-actions-ranking-v90';p=O/'registration.json';r=json.loads(p.read_text());review=R/'output/analysis/query-actions-v90-prefit-review.json'
assert verify_frozen_source(E)==r['engine_receipt']=='d0fa6e6e3b80eb432d19b73449211e7cee26df235b976e59f91f7594c43f6259'
assert sha('/private/tmp/ken-query-actions-ranking-v90.py')==r['script_sha256']=='94b242dc2c5878713c83797b1c4a410e9d191f9e87beffafff09e414c38dbdf9'
assert sha(p)=='9bdfcef4747b1d261fd2335182b83005d12659c49f35ab2cb18b18bc2a8de436'
assert r['pre_fit_ready']and not r['folds']and not r['results']and not list(O.glob('*-numeric.json'))
for key in ('inputs','source_bindings','parent_bindings'):
 assert all(sha(path)==digest for path,digest in r[key].items()),key
assert len(r['training_sets'])==16 and all(sha(O/(repo+'-training-rows.npz'))==v['sha256']for repo,v in r['training_sets'].items())
assert not (O/'PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert not (R/'output/analysis/listwise-linear-ranking-v88/PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert review.is_file()
audit=json.loads(review.read_text());assert audit['status']=='PRE-FIT_APTO_FOR_FIXED90_ONLY'
assert audit['approval_binding_fields']=={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p)}
a={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p),'independent_review':str(review),'independent_review_sha256':sha(review),'scope':'Root accepts independently reviewed90 pre-fit artifacts only. Original400/16 whole-repository exclusions/objective/acceptance unchanged.'}
(O/'PRE-FIT-REVIEW-ACCEPTED.json').write_text(json.dumps(a,indent=2));print(json.dumps(a,indent=2))
