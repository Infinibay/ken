"""Evidence-only source completion; original ALL400 gold is read after answers."""
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import ken

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from complete_owned_context import complete_owned_context
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.intent import interpret
from ken.retrieval.model import CodeMatch, SearchRequest
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/complete-owned-context-v72'
OUT.mkdir(exist_ok=False)
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
PRIOR = ROOT/'output/analysis/source7-context-views-ranking-v69/contract_body251'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
bindings = validate_replay_parent(PARENT, POOL)
requests = {}
for path in sorted((POOL/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
assert len(requests) == 400
roots = {k: Path(v) for k, v in json.loads(
    (ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
pools = load_pools(POOL, requests)
prior = {r['id']: r for r in map(json.loads, (PRIOR/'responses.jsonl').read_text().splitlines())}
data = np.load(ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz')
qids = data['qid']  # Reuse row IDs only; no y/eligible label is read here.
scores = np.load(PRIOR/'scores.npy')
assert set(requests) == set(prior) == set(qids)
assert len(scores) == len(qids) == 167360
manifest = {'scope': 'ALL400 evidence-only prepared control, exact unchanged69 owner order/scores; '
            'no API/profile acceptance claim', 'engine_receipt': receipt,
    'script_sha256': sha(__file__), 'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-complete-owned-context-v72.md'),
    'inputs': {str(p): sha(p) for p in (PRIOR/'scores.npy', PRIOR/'responses.jsonl',
         ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz')},
    'parent_bindings': bindings, 'changed_evidence_queries': []}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
responses = []
for qid, row in requests.items():
    request = SearchRequest(**row['request'])
    pool = pools[qid]
    prediction = scores[qids == qid]
    assert len(prediction) == len(pool)
    order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0), -prediction[i], i))
    matches = [CodeMatch(pool[i].entity, float(prediction[i]), pool[i].passages,
        pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
    baseline = {'id': qid, **present(matches, roots[row['repo_id']], request,
                                  profile_version=prior[qid]['profile_version']).to_dict()}
    assert baseline == prior[qid]
    if not interpret(request).identity:
        for index, match in enumerate(matches[:request.limit]):
            if not match.signals.get('exact'):
                matches[index] = complete_owned_context(match, roots[row['repo_id']])
    response = {'id': qid, **present(matches, roots[row['repo_id']], request,
        profile_version=prior[qid]['profile_version']).to_dict()}
    assert [(r['path'], r['entity'], r['ranking_score']) for r in response['results']] == [
        (r['path'], r['entity'], r['ranking_score']) for r in baseline['results']]
    if response != baseline:
        manifest['changed_evidence_queries'].append(qid)
    response['profile_version'] = hashlib.sha256(
        (prior[qid]['profile_version']+'complete-owned-research-v72:'+receipt).encode()).hexdigest()
    responses.append(response)
assert len(responses) == len({r['id'] for r in responses}) == 400
(OUT/'responses.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in responses))
assert bindings == validate_replay_parent(PARENT, POOL)
assert all(sha(p) == digest for p, digest in manifest['inputs'].items())
assert verify_frozen_source(ENGINE) == receipt
# Only the evaluator joins the original immutable relevance references.
from ken.bench.retrieval import evaluate
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
report = evaluate(cases, responses, roots=roots)
(OUT/'report.json').write_text(json.dumps(report, indent=2))
manifest.update(result={'strict': report['strict_top1'], 'identity': report['identity_top1'],
                        'missing': report['missing_response_ids']}, responses_sha256=sha(OUT/'responses.jsonl'))
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'changed_queries': len(manifest['changed_evidence_queries']), **manifest['result']}), flush=True)
