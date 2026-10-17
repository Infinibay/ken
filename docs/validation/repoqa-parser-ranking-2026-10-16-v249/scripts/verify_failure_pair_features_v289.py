"""Verify saved feature-pair scores against the exact production numeric model."""
from pathlib import Path
import gzip,hashlib,json,sys
import numpy as np
clean=Path('/Users/andres/.codex/worktrees/compact-default-output/ken');sys.path.insert(0,str(clean/'src'))
from ken.retrieval.numeric_ranker import NumericRanker
base=Path.cwd()/'output/analysis/repoqa-diagnosis-v236';path=base/'failure-pair-features-v286.json';value=json.loads(path.read_text());registry=json.loads((clean/'src/ken/retrieval/data/production-rank-models.json').read_text());model=NumericRanker.from_dict(json.loads(gzip.decompress((clean/'src/ken/retrieval/data'/registry['native']['file']).read_bytes())));assert model.fingerprint==registry['native']['fingerprint']==value['model_fingerprint'];assert list(model.features)==value['feature_names'];checked=[]
for row in value['rows']:
 for side in ('gold','chosen'):
  owner=row[side]
  if owner is None:continue
  score=float(model.predict(np.asarray([owner['feature_values']]))[0]);assert abs(score-owner['score'])<1e-12,(row['id'],side,score,owner['score']);checked.append(abs(score-owner['score']))
assert len(checked)==145
out={'cases':value['cases'],'complete_pairs':value['pairs'],'feature_count':value['feature_count'],'verified_scores':len(checked),'max_absolute_score_difference':max(checked),'model_fingerprint':model.fingerprint,'features_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'producer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'reserve':'CLOSED','interpretation':'Every exported gold/chosen numeric score reproduces, including chosen scores for three missing/noncanonical reference identities. No reranking, model inference, fitting or new relevance score.'};(base/'failure-pair-feature-verification-v289.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
