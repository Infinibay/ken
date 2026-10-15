import hashlib,json,sys
from pathlib import Path
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');E=R/'output/frozen/cpu-choice-trees-v89';sys.path.insert(0,str(E/'src'))
from ken.bench.source_receipts import verify_frozen_source
sha=lambda p:hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
O=R/'output/analysis/choice-trees-ranking-v89';p=O/'registration.json';r=json.loads(p.read_text());review=R/'output/analysis/choice-trees-v89-prefit-review.json'
assert verify_frozen_source(E)==r['engine_receipt']=='5ab6da502c32b858383bec48b06e37b571ef7a74d4e2ae405ffff9f1755273c2'
assert sha('/private/tmp/ken-choice-trees-ranking-v89.py')==r['script_sha256']=='7b2ea86863afc3c6281be8bbb605b398b3d36571438f88911bb778504d744aa3'
assert sha(p)=='851442265fee37e8b5dd2e31e0e1a7304a315a9aa7089fef9a02fdc3f73ff511'
assert r['pre_fit_ready']and not r['folds']and not r['results']and not list(O.glob('*-numeric.json'))
for key in ('inputs','source_bindings','parent_bindings'):
 assert all(sha(path)==digest for path,digest in r[key].items()),key
assert len(r['normalizers'])==16 and all(sha(O/(repo+'-normalizer.npz'))==v['sha256']for repo,v in r['normalizers'].items())
assert not (O/'PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert not (R/'output/analysis/listwise-linear-ranking-v88/PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert review.is_file()
audit=json.loads(review.read_text());assert audit['status']=='PRE-FIT_APTO_FOR_FIXED89_ONLY'
assert audit['approval_binding_fields']=={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p)}
a={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p),'independent_review':str(review),'independent_review_sha256':sha(review),'scope':'Root accepts independently reviewed89 pre-fit artifacts only. Original400/16 whole-repository exclusions/objective/acceptance unchanged.'}
(O/'PRE-FIT-REVIEW-ACCEPTED.json').write_text(json.dumps(a,indent=2));print(json.dumps(a,indent=2))
