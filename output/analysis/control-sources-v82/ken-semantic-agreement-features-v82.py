"""All source owner contrast coordinates first; then fixed315 public features."""
import hashlib
import itertools
import json
import sqlite3
import sys
from pathlib import Path

import ken
import numpy as np

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from query_semantics import QUERY_CONTRASTS, SemanticContrasts
from semantic_agreement import agreement_features
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import EntityKey

BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
QUERY = ROOT/'output/analysis/query-semantics-features-v80'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
OUT = ROOT/'output/analysis/semantic-agreement-features-v82'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
assert sha(QUERY/'registration.json') == 'a4c6bbfad9a06fadf2171c7eed69f9e563ae4dc689a3194326da1be096dd8dbb'
query_reg = json.loads((QUERY/'registration.json').read_text())
assert query_reg['complete'] is True and len(query_reg['query_repos']) == 16
assert sha(VIEWS/'registration.json') == 'd4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
source_reg = json.loads((VIEWS/'registration.json').read_text())
assert len(source_reg['source_repos']) == 16
assert sha(QUERY/'axes.npy') == query_reg['query_semantics']['axes_sha256']
assert sha(ENGINE/'experiments/search-engine/query_semantics.py') == query_reg['query_semantics']['helper_sha256']
assert tuple(map(tuple, json.loads((QUERY/'templates.json').read_text()))) == QUERY_CONTRASTS
assert sha(QUERY/'templates.json') == query_reg['query_semantics']['templates_sha256']
assert sha(VIEWS/'model-registration.json') == source_reg['model_registration_sha256']
model_path = ROOT/'output/models/cpu-context-registration-v42.json'
assert sha(model_path) == source_reg['original_model_registration_sha256'] == query_reg['query_semantics']['model_registration_sha256']
model = json.loads(model_path.read_text())
for name, digest in model['artifacts'].items():
    assert sha(Path(model['root'])/name) == digest
contrasts = SemanticContrasts(np.load(QUERY/'axes.npy'))
roots = {name: Path(path) for name, path in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
manifest = {'scope': 'complete16 source7 implementation69 coordinates before query features; fixed80 axes; then315 features; no encoder calls or new labels',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-semantic-agreement-v82.md'),
    'source_repos': {}, 'query_repos': {}, 'complete': False,
    'query_semantics': query_reg['query_semantics'], 'query_semantics_revision': query_reg['query_semantics_revision'],
    'source_registration_sha256': sha(VIEWS/'registration.json'),
    'query_features_registration_sha256': sha(QUERY/'registration.json'), 'public_inputs': query_reg['public_inputs']}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
for repo, metadata in sorted(source_reg['source_repos'].items()):
    source_db, vectors_path = VIEWS/(repo+'-source.db'), VIEWS/(repo+'-vectors.npy')
    full_path = BASE/'context'/(repo+'.db')
    assert sha(source_db) == metadata['source_db_sha256']
    assert sha(vectors_path) == metadata['vectors_sha256']
    assert sha(full_path) == metadata['base_full_context_sha256']
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['source_files'].items())
    with sqlite3.connect(f'file:{full_path}?mode=ro', uri=True) as db:
        expected = dict(db.execute('SELECT entity,source_hash FROM owners'))
    with sqlite3.connect(f'file:{source_db}?mode=ro', uri=True) as db:
        entries = db.execute("SELECT entity,source_hash,vector_index FROM owners WHERE view='implementation' ORDER BY entity").fetchall()
    assert len(entries) == len(expected) == metadata['owners']
    assert {entity: digest for entity, digest, _ in entries} == expected
    vectors = np.load(vectors_path, mmap_mode='r')
    assert vectors.dtype == np.float32 and vectors.shape == (metadata['unique_texts'], 768)
    coordinates = np.stack([contrasts.project(vectors[index]) for _, _, index in entries])
    assert coordinates.shape == (len(entries), 16) and np.isfinite(coordinates).all()
    destination = OUT/(repo+'-owners.npz')
    np.savez_compressed(destination, entity=[entry[0] for entry in entries],
        source_hash=[entry[1] for entry in entries], coordinates=coordinates)
    manifest['source_repos'][repo] = {**metadata, 'coordinates_sha256': sha(destination),
        'coordinates_bytes': coordinates.nbytes}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'source_complete': repo, 'owners': len(entries)}), flush=True)
assert sum(item['owners'] for item in manifest['source_repos'].values()) == 50967
# No public query text/vector/feature matrix was read before all source owners.
assert sha(PARENT/'registration.json') == query_reg['parent_features_registration_sha256']
bindings = validate_replay_parent(PARENT, BASE)
assert len(bindings) == 51
parent_reg = json.loads((PARENT/'registration.json').read_text())
features = (*query_reg['features'],
    *(f'owner_semantic_{name}' for name, _, _ in QUERY_CONTRASTS),
    *(f'semantic_agreement_{name}' for name, _, _ in QUERY_CONTRASTS),
    *(f'semantic_distance_{name}' for name, _, _ in QUERY_CONTRASTS))
assert len(features) == len(set(features)) == 315
manifest['features'] = features
manifest['parent_features_registration_sha256'] = sha(PARENT/'registration.json')
requests = {}
for path in sorted((BASE/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
assert len(requests) == 400
pools = load_pools(BASE, requests)
manifest['exact_numeric_bypasses'] = 0
for repo in sorted(roots):
    owner_path, query_path = OUT/(repo+'-owners.npz'), QUERY/(repo+'.npz')
    assert sha(owner_path) == manifest['source_repos'][repo]['coordinates_sha256']
    assert sha(query_path) == query_reg['query_repos'][repo]['output_sha256']
    with np.load(owner_path) as source:
        coordinate_map = {EntityKey(**json.loads(str(entity))): (str(digest), coords)
            for entity, digest, coords in zip(source['entity'], source['source_hash'], source['coordinates'], strict=True)}
    with np.load(query_path) as source:
        qids, indexes, prefix = source['qid'], source['index'], source['x']
    with np.load(PARENT/(repo+'.npz')) as source:
        assert np.array_equal(qids, source['qid']) and np.array_equal(indexes, source['index'])
        assert np.array_equal(prefix[:, :251], source['x'])
    extra = []
    for qid, group in itertools.groupby(range(len(qids)), key=lambda i: str(qids[i])):
        rows = list(group)
        pool = pools[qid]
        assert len(pool) == len(rows) and np.array_equal(indexes[rows], np.arange(len(pool)))
        query = prefix[rows[0], 251:]
        assert np.array_equal(prefix[rows, 251:], np.broadcast_to(query, (len(pool), 16)))
        if len(pool) == 1 and pool[0].signals.get('exact'):
            added = np.zeros((1, 48))
            manifest['exact_numeric_bypasses'] += 1
        else:
            assert all(coordinate_map[item.entity][0] == item.passages[0].source_hash for item in pool)
            added = agreement_features(query, np.stack([coordinate_map[item.entity][1] for item in pool]))
        extra.extend(added)
    matrix = np.column_stack((prefix, extra))
    assert matrix.shape == (len(qids), 315) and np.isfinite(matrix).all()
    assert np.array_equal(matrix[:, :267], prefix)
    destination = OUT/(repo+'.npz')
    np.savez_compressed(destination, x=matrix, qid=qids, index=indexes)
    manifest['query_repos'][repo] = {'queries': len(set(qids)), 'rows': len(qids),
        'parent_features_sha256': sha(PARENT/(repo+'.npz')), 'query_features_sha256': sha(query_path),
        'output_sha256': sha(destination)}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'features_complete': repo, 'rows': len(qids)}), flush=True)
assert manifest['exact_numeric_bypasses'] == 37
assert bindings == validate_replay_parent(PARENT, BASE)
assert len(validate_replay_parent(PARENT, BASE, extension=OUT)) == 68
assert sha(QUERY/'registration.json') == manifest['query_features_registration_sha256']
assert all(sha(path) == digest for path, digest in manifest['public_inputs'].items())
for repo, metadata in manifest['source_repos'].items():
    assert sha(VIEWS/(repo+'-source.db')) == metadata['source_db_sha256']
    assert sha(VIEWS/(repo+'-vectors.npy')) == metadata['vectors_sha256']
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['source_files'].items())
assert verify_frozen_source(ENGINE) == receipt
manifest['complete'] = True
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
