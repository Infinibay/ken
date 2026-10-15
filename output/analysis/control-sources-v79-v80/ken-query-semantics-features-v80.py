"""Query-independent contrast assets first; then fixed267 public query features."""
import gc
import hashlib
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import ken
ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from query_semantics import QUERY_CONTRASTS, SemanticContrasts
from contextual_run import CPUContextEncoder
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source

BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
OUT = ROOT/'output/analysis/query-semantics-features-v80'
MODEL = ROOT/'output/models/cpu-context-registration-v42.json'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
source_metadata = json.loads((VIEWS/'registration.json').read_text())
assert sha(MODEL) == source_metadata['original_model_registration_sha256']
model_registration = json.loads(MODEL.read_text())
context = CPUContextEncoder(model_registration)
positive, negative = [], []
for name, a, b in QUERY_CONTRASTS:
    positive.append(context.embed_query(a))
    negative.append(context.embed_query(b))
assert len(QUERY_CONTRASTS) == 16 and len(context.calls) == 32
contrasts = SemanticContrasts.from_pairs(positive, negative)
np.save(OUT/'axes.npy', contrasts.axes)
np.savez(OUT/'template-vectors.npz', positive=positive, negative=negative)
(OUT/'templates.json').write_text(json.dumps(QUERY_CONTRASTS, indent=2))
np.testing.assert_array_equal(SemanticContrasts(np.load(OUT/'axes.npy')).axes, contrasts.axes)
identity = {'model_registration_sha256': sha(MODEL), 'model': model_registration['spec'],
    'templates_sha256': sha(OUT/'templates.json'), 'axes_sha256': sha(OUT/'axes.npy'),
    'raw_vectors_sha256': sha(OUT/'template-vectors.npz'),
    'normalization': 'float64-scaled-unit-endpoints,difference,scaled-unit-axis;one-query-scaled-unit-project-v1',
    'helper_sha256': sha(ENGINE/'experiments/search-engine/query_semantics.py')}
manifest = {'scope': 'ALL400 original queries/251parent plus16genericsemanticquerycolumns; no extra inference encoder;fixed before fits',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-query-semantics-v80.md'),
    'query_semantics': identity, 'query_semantics_revision': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
    'template_cpu_calls': context.calls, 'source_repos': {}, 'query_repos': {}, 'complete': False}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'generic_templates_complete': 32, 'axes': list(contrasts.axes.shape), 'bytes': contrasts.axes.nbytes}), flush=True)
del context
gc.collect()
# No real query was read before complete template assets were registered.
bindings = validate_replay_parent(PARENT, BASE)
assert len(bindings) == 51
parent_reg = json.loads((PARENT/'registration.json').read_text())
manifest['source_repos'] = parent_reg['source_repos']
manifest['parent_features_registration_sha256'] = sha(PARENT/'registration.json')
manifest['parent_bindings'] = bindings
features = (*parent_reg['features'], *(f'query_semantic_{name}' for name, _, _ in QUERY_CONTRASTS))
assert len(features) == len(set(features)) == 267
manifest['features'] = features
requests = {}
for file in sorted((BASE/'requests').glob('*.jsonl')):
    for row in map(json.loads, file.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
pools = load_pools(BASE, requests)
saved = {row['id']: row for row in map(json.loads, (BASE/'candidates.jsonl').read_text().splitlines())}
qfile = ROOT/'output/analysis/coderank-public-queries-v31/vectors.npz'
expanded_file = ROOT/'output/analysis/es-en-control-v16/queries.jsonl'
audit = ROOT/'output/analysis/query-input-recode-v64/registration.json'
for path in (qfile, expanded_file):
    assert sha(path) == parent_reg['public_inputs'][str(path)]
with np.load(qfile) as query_data:
    qids, vectors = query_data['qid'], query_data['expanded']
queries = {str(qid): vectors[i] for i, qid in enumerate(qids)}
expanded = {row['id']: row['expanded'] for row in map(json.loads, expanded_file.read_text().splitlines())}
assert set(queries) == set(saved) == set(requests) == set(expanded) and len(queries) == 400
manifest['public_inputs'] = {str(path): sha(path) for path in (qfile, expanded_file, audit)}
manifest['exact_numeric_bypasses'] = 0
for repo in sorted(parent_reg['query_repos']):
    with np.load(PARENT/f'{repo}.npz') as parent:
        qids, indexes, prefix = parent['qid'], parent['index'], parent['x']
    extra = []
    for qid, group in itertools.groupby(range(len(qids)), key=lambda i: str(qids[i])):
        rows = list(group)
        pool = pools[qid]
        assert len(rows) == len(pool) and np.array_equal(indexes[rows], np.arange(len(pool)))
        if len(pool) == 1 and pool[0].signals.get('exact'):
            vector = np.zeros(16)
            manifest['exact_numeric_bypasses'] += 1
        else:
            assert saved[qid]['expanded_query'] == expanded[qid]
            vector = contrasts.project(queries[qid])
            assert np.array_equal(vector, SemanticContrasts(np.load(OUT/'axes.npy')).project(queries[qid]))
        extra.extend(np.broadcast_to(vector, (len(pool), 16)))
    matrix = np.column_stack((prefix, extra))
    assert matrix.shape == (len(qids), 267) and np.isfinite(matrix).all()
    np.savez_compressed(OUT/f'{repo}.npz', x=matrix, qid=qids, index=indexes)
    manifest['query_repos'][repo] = {'queries': len(set(qids)), 'rows': len(qids),
        'parent_features_sha256': sha(PARENT/f'{repo}.npz'), 'output_sha256': sha(OUT/f'{repo}.npz')}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'features_complete': repo, 'rows': len(qids)}), flush=True)
assert manifest['exact_numeric_bypasses'] == 37
assert validate_replay_parent(PARENT, BASE) == bindings
assert len(validate_replay_parent(PARENT, BASE, extension=OUT)) == 68
assert verify_frozen_source(ENGINE) == receipt
assert all(sha(path) == digest for path, digest in manifest['public_inputs'].items())
for name, digest in model_registration['artifacts'].items():
    assert sha(Path(model_registration['root'])/name) == digest
assert sha(OUT/'axes.npy') == identity['axes_sha256']
manifest['complete'] = True
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
