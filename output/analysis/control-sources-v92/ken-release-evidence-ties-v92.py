import hashlib,json,sys
from pathlib import Path
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace');E=R/'output/frozen/cpu-evidence-ties-v92';sys.path.insert(0,str(E/'src'))
from ken.bench.source_receipts import verify_frozen_source
sha=lambda p:hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
O=R/'output/analysis/evidence-ties-ranking-v92';p=O/'registration.json';r=json.loads(p.read_text());review=R/'output/analysis/evidence-ties-v92-prefit-review.json'
assert verify_frozen_source(E)==r['engine_receipt']=='dc63117ba6e8ab49e53db5781ccc7b96ab8253e0a70817ab56b1bbab47573d8c'
assert sha('/private/tmp/ken-evidence-ties-ranking-v92.py')==r['script_sha256']=='2d79e009c5e0b54beb4bebd82cee0d160ba45826320c963e2f1dc643d4e98c0f'
assert sha(p)=='f385c8ddfe3e367e631ebd6abe7849102fa7d1638ff8ed24aec1036dc2c12bd6'
assert r['pre_fit_ready']and not r['folds']and not r['results']and not list(O.glob('*-numeric.json'))
for key in ('inputs','source_bindings','parent_bindings'):
 assert all(sha(path)==digest for path,digest in r[key].items()),key
assert len(r['training_sets'])==16 and all(sha(O/(repo+'-training-rows.npz'))==v['sha256']for repo,v in r['training_sets'].items())
assert not (O/'PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert not (R/'output/analysis/listwise-linear-ranking-v88/PRE-FIT-REVIEW-ACCEPTED.json').exists()
assert review.is_file()
audit=json.loads(review.read_text());assert audit['status']=='PRE-FIT_APTO_FOR_FIXED92_ONLY'
assert audit['approval_binding_fields']=={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p)}
a={'engine_receipt':r['engine_receipt'],'controller_sha256':r['script_sha256'],'pre_fit_registration_sha256':sha(p),'independent_review':str(review),'independent_review_sha256':sha(review),'scope':'Root accepts independently reviewed92 pre-fit artifacts only. Original400/16 whole-repository exclusions/objective/acceptance unchanged.'}
(O/'PRE-FIT-REVIEW-ACCEPTED.json').write_text(json.dumps(a,indent=2));print(json.dumps(a,indent=2))
