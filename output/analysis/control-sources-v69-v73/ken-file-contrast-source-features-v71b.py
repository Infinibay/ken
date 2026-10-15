"""Source-only per-file backgrounds, then bound ALL400 public candidate features."""
import gc
import hashlib
import itertools
import json
import resource
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import ken

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from file_contrast import COMMONNESS, CONTRASTS, FileContrast
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import EntityKey

BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
OUT = ROOT/'output/analysis/file-contrast-features-v71b'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_rows(repo):
    path = BASE/'context'/f'{repo}.db'
    assert sha(path) == source_reg['context_repos'][repo]['context_index_sha256']
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    rows = db.execute('SELECT entity,text_hash,source_hash,vector FROM owners '
                      'JOIN vectors ON text_hash=hash ORDER BY entity').fetchall()
    db.close()
    entities = [EntityKey(**json.loads(row[0])) for row in rows]
    assert len(rows) == len(set(entities)) == source_reg['context_repos'][repo]['owners']
    vectors = np.stack([np.frombuffer(row[3], dtype=np.float32) for row in rows])
    return rows, entities, FileContrast([e.path for e in entities], vectors)


receipt = verify_frozen_source(ENGINE)
source_reg = json.loads((BASE/'registration.json').read_text())
roots = {k: Path(v) for k, v in json.loads(
    (ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(source_reg['source_repos']) == len(source_reg['context_repos']) == len(roots) == 16
manifest = {
    'scope': 'ALL source7 owners prepare file-local backgrounds before query access; '
             'ALL400 fixed pools and251 parent; prepared only, no API/acceptance claim',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-file-contrast-v71.md'),
    'source_registration_sha256': sha(BASE/'registration.json'),
    'encoder': source_reg['encoder'], 'source_repos': {}, 'query_repos': {},
}
for repo, root in sorted(roots.items()):
    started = time.perf_counter()
    for path, digest in source_reg['source_repos'][repo]['file_hashes'].items():
        assert sha(root/path) == digest
    rows, entities, contrast = source_rows(repo)
    np.savez_compressed(OUT/f'{repo}-source.npz',
        entity=[r[0] for r in rows], source_hash=[r[2] for r in rows],
        text_hash=[r[1] for r in rows], paths=contrast.paths, groups=contrast.groups,
        means=contrast.means, topics=contrast.topics,
        commonness=contrast.commonness(np.arange(len(rows))))
    manifest['source_repos'][repo] = {
        'owners': len(rows), 'files': len(contrast.paths),
        'source_files': source_reg['context_repos'][repo]['source_files'],
        'source_generation': source_reg['context_repos'][repo]['generation'],
        'input_context_sha256': sha(BASE/'context'/f'{repo}.db'),
        'prepared_sha256': sha(OUT/f'{repo}-source.npz'),
        'ms': (time.perf_counter()-started)*1000,
        'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'source_complete': repo, 'owners': len(rows)}), flush=True)
    del rows, entities, contrast
    gc.collect()
assert len(manifest['source_repos']) == 16
# No labels are read by this producer. Cached feature/pool identity is validated
# before any reuse, including same-file owner swaps with equal source hashes.
bindings = validate_replay_parent(PARENT, BASE)
assert len(bindings) == 51
parent_reg = json.loads((PARENT/'registration.json').read_text())
requests = {}
for path in sorted((BASE/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
assert len(requests) == 400
pools = load_pools(BASE, requests)
saved = {r['id']: r for r in map(json.loads, (BASE/'candidates.jsonl').read_text().splitlines())}
qfile = ROOT/'output/analysis/coderank-public-queries-v31/vectors.npz'
qdata = np.load(qfile)
queries = {str(qid): (qdata['original'][i], qdata['expanded'][i]) for i, qid in enumerate(qdata['qid'])}
expanded_file = ROOT/'output/analysis/es-en-control-v16/queries.jsonl'
expanded = {r['id']: r['expanded'] for r in map(json.loads, expanded_file.read_text().splitlines())}
audit = ROOT/'output/analysis/query-input-recode-v64/registration.json'
assert set(requests) == set(queries) == set(saved) == set(expanded)
features = (*parent_reg['features'], *(f'file_{contrast}_{query}_{stat}'
    for contrast in CONTRASTS for query in ('original', 'expanded')
    for stat in ('raw', 'to_max', 'range_relative', 'reciprocal_rank')),
    *(f'file_{name}' for name in COMMONNESS))
assert len(features) == 272
manifest.update(features=features, parent_bindings=bindings,
    public_inputs={str(p): sha(p) for p in (qfile, expanded_file, audit)},
    original_query_binding_count=800, exact_numeric_bypasses=0)
for repo in sorted(roots):
    rows, entities, contrast = source_rows(repo)
    with np.load(OUT/f'{repo}-source.npz') as prepared:
        assert sha(OUT/f'{repo}-source.npz') == manifest['source_repos'][repo]['prepared_sha256']
        assert np.array_equal(prepared['entity'], [r[0] for r in rows])
        for name in ('paths', 'groups', 'means', 'topics'):
            assert np.array_equal(prepared[name], getattr(contrast, name))
        assert np.array_equal(prepared['commonness'], contrast.commonness(np.arange(len(rows))))
    by_entity = {entity: i for i, entity in enumerate(entities)}
    with np.load(PARENT/f'{repo}.npz') as parent:
        qids, extra = parent['qid'], []
        for qid, indexes in itertools.groupby(range(len(qids)), key=lambda i: str(qids[i])):
            indexes = list(indexes)
            pool = pools[qid]
            assert len(indexes) == len(pool)
            bypass = len(pool) == 1 and bool(pool[0].signals.get('exact'))
            if bypass:
                extra.extend(np.zeros((1, 21)))
                manifest['exact_numeric_bypasses'] += 1
                continue
            assert saved[qid]['expanded_query'] == expanded[qid]
            owner_ids = [by_entity[c.entity] for c in pool]
            assert all(rows[i][2] == c.passages[0].source_hash for i, c in zip(owner_ids, pool))
            values_by_query = [contrast.score(query, owner_ids) for query in queries[qid]]
            columns = []
            for ci in range(len(CONTRASTS)):
                for values in values_by_query:
                    scores = values[:, ci]
                    ranks = np.empty(len(scores))
                    ranks[np.argsort(-scores, kind='stable')] = np.arange(1, len(scores)+1)
                    columns.extend((scores, scores-scores.max(),
                        (scores-scores.min())/max(1e-9, float(np.ptp(scores))), 1/ranks))
            extra.extend(np.column_stack((*columns, contrast.commonness(owner_ids))))
        matrix = np.column_stack((parent['x'], extra))
        assert matrix.shape == (len(qids), 272) and np.isfinite(matrix).all()
        np.savez_compressed(OUT/f'{repo}.npz', x=matrix, qid=qids, index=parent['index'])
        manifest['query_repos'][repo] = {'queries': len(set(qids)), 'rows': len(qids),
            'parent_features_sha256': sha(PARENT/f'{repo}.npz'),
            'output_sha256': sha(OUT/f'{repo}.npz')}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'features_complete': repo, 'rows': len(qids)}), flush=True)
    del rows, entities, contrast, matrix, extra
    gc.collect()
assert bindings == validate_replay_parent(PARENT, BASE)
assert all(sha(p) == digest for p, digest in manifest['public_inputs'].items())
assert verify_frozen_source(ENGINE) == receipt
