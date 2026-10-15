"""All source7 bare-owned implementations first, then bound400 source69 features."""
import collections
import dataclasses
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
from contextual_run import CPUContextEncoder, registered_context_spec
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES, contextual_features
from ken.retrieval.description import describe_owner
from ken.retrieval.model import Candidate, EntityKey
from ken.retrieval.storage import load_passage_map

BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
SOURCE_VIEWS = ROOT/'output/analysis/context-views-source7-v69'
OUT = ROOT/'output/analysis/bare-owned-code-features-v78'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
source_reg = json.loads((BASE/'registration.json').read_text())
source_views = json.loads((SOURCE_VIEWS/'registration.json').read_text())
parent_metadata = json.loads((PARENT/'registration.json').read_text())
assert sha(BASE/'registration.json') == parent_metadata['public_inputs'][str(BASE/'registration.json')]
assert sha(SOURCE_VIEWS/'registration.json') == parent_metadata['parent_source_registration_sha256']
roots = {k: Path(v) for k, v in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(roots) == len(source_reg['source_repos']) == len(source_reg['context_repos']) == 16
original_model_file = ROOT/'output/models/cpu-context-registration-v42.json'
assert sha(original_model_file) == source_views['original_model_registration_sha256']
original_model = json.loads(original_model_file.read_text())
projection = 'raw-owned-implementation-without-synthetic-header-prefix512-v1'
model_reg = dict(original_model, document_projection=projection)
model_reg['spec'] = dataclasses.asdict(registered_context_spec(model_reg))
(OUT/'model-registration.json').write_text(json.dumps(model_reg, indent=2))
encoder = CPUContextEncoder(model_reg)
manifest = {'scope': 'ALL16 source7 owned implementation projection beforequery;noheader/newmodel;all400bound251parent+8barecodefeatures',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-bare-owned-code-v78.md'),
    'source_registration_sha256': sha(BASE/'registration.json'),
    'original_model_registration_sha256': sha(original_model_file),
    'model_registration_sha256': sha(OUT/'model-registration.json'),
    'source_projection': projection, 'query_model': original_model['spec'],
    'source_model': model_reg['spec'], 'source_repos': {}, 'query_repos': {}}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
for repo, root in sorted(roots.items()):
    started = time.perf_counter()
    index = BASE/'indices'/f'{repo}.db'
    metadata = source_reg['source_repos'][repo]
    assert sha(index) == metadata['new_source_index_sha256']
    assert all(sha(root/path) == digest for path, digest in metadata['file_hashes'].items())
    conn = sqlite3.connect(f'file:{index}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    assert {r[0] for r in conn.execute('SELECT DISTINCT extractor_version FROM ci_retrieval_files')} == {7}
    groups = collections.defaultdict(list)
    for passage in load_passage_map(conn).values():
        groups[passage.entity].append(passage)
    generation = conn.execute("SELECT value FROM meta WHERE key='retrieval_generation'").fetchone()[0]
    conn.close()
    assert len(groups) == metadata['owners']
    texts, lookup, owners = [], {}, []
    for entity, passages in groups.items():
        desc = describe_owner(passages)
        assert desc.source_hash == metadata['file_hashes'][entity.path]
        text = desc.fields['implementation']
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest not in lookup:
            lookup[digest] = len(texts)
            texts.append(text)
        row = lookup[digest]
        assert texts[row] == text
        identity = json.dumps({'path': entity.path, **entity.to_dict()}, sort_keys=True, separators=(',', ':'))
        owners.append((identity, desc.source_hash, digest, row))
    source_db = OUT/f'{repo}-source.db'
    db = sqlite3.connect(source_db)
    db.execute('CREATE TABLE owners(entity TEXT PRIMARY KEY,source_hash TEXT,text_hash TEXT,vector_index INT)')
    db.execute('CREATE TABLE texts(vector_index INT PRIMARY KEY,text_hash TEXT,text TEXT)')
    db.executemany('INSERT INTO owners VALUES (?,?,?,?)', owners)
    db.executemany('INSERT INTO texts VALUES (?,?,?)', [(i, hashlib.sha256(text.encode()).hexdigest(), text) for i, text in enumerate(texts)])
    db.commit()
    db.close()
    vector_path = OUT/f'{repo}-vectors.npy'
    vectors = np.lib.format.open_memmap(vector_path, mode='w+', dtype=np.float32, shape=(len(texts), 768))
    token_count = 0
    for i, text in enumerate(texts):
        value = encoder.embed_passages([text])[0]
        norm = np.linalg.norm(value)
        assert value.shape == (768,) and np.isfinite(value).all() and norm > 1e-9
        vectors[i] = (value/norm).astype(np.float32)
        token_count += encoder.calls[-1]['tokens']
        if i % 256 == 0:
            vectors.flush()
            encoder.calls.clear()
            print(json.dumps({'source_progress': repo, 'texts': i, 'total': len(texts)}), flush=True)
    vectors.flush()
    del vectors
    manifest['source_repos'][repo] = {'owners': len(owners), 'unique_texts': len(texts),
        'empty_implementation_owners': sum(not texts[row] for _, _, _, row in owners),
        'input_index_sha256': sha(index), 'source_generation': generation,
        'source_files': metadata['file_hashes'], 'source_db_sha256': sha(source_db),
        'vectors_sha256': sha(vector_path), 'vector_bytes': vector_path.stat().st_size,
        'mean_tokens': token_count/len(texts), 'ms': (time.perf_counter()-started)*1000,
        'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    assert sha(index) == metadata['new_source_index_sha256']
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'source_complete': repo, 'owners': len(owners), 'texts': len(texts)}), flush=True)
    encoder.calls.clear()
    del groups, texts, lookup, owners
    gc.collect()
assert len(manifest['source_repos']) == 16
# Query encoding remains exactly the old model/prefix; no new query/model calls.
del encoder
gc.collect()
bindings = validate_replay_parent(PARENT, BASE)
assert len(bindings) == 51
parent_reg = json.loads((PARENT/'registration.json').read_text())
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
with np.load(qfile) as qdata:
    query_ids, original_queries, expanded_queries = qdata['qid'], qdata['original'], qdata['expanded']
queries = {str(qid): (original_queries[i], expanded_queries[i]) for i, qid in enumerate(query_ids)}
expanded = {row['id']: row['expanded'] for row in map(json.loads, expanded_file.read_text().splitlines())}
assert len(requests) == 400 and set(requests) == set(queries) == set(saved) == set(expanded)
features = (*parent_reg['features'], *(f'bare_{name}' for name in CONTEXTUAL_FEATURES))
assert len(features) == 259
manifest.update(features=features, parent_features_registration_sha256=sha(PARENT/'registration.json'),
    parent_bindings=bindings, public_inputs={str(path): sha(path) for path in (qfile, expanded_file, audit)},
    exact_numeric_bypasses=0, original_query_binding_count=800)
for repo in sorted(roots):
    metadata = manifest['source_repos'][repo]
    assert sha(OUT/f'{repo}-source.db') == metadata['source_db_sha256']
    assert sha(OUT/f'{repo}-vectors.npy') == metadata['vectors_sha256']
    db = sqlite3.connect(f'file:{OUT/(repo+"-source.db")}?mode=ro', uri=True)
    owner_rows = {EntityKey(**json.loads(row[0])): (row[1], row[3]) for row in db.execute('SELECT * FROM owners')}
    db.close()
    vectors = np.load(OUT/f'{repo}-vectors.npy', mmap_mode='r')
    with np.load(PARENT/f'{repo}.npz') as parent:
        qids, indexes, prefix = parent['qid'], parent['index'], parent['x']
    extra = []
    for qid, group in itertools.groupby(range(len(qids)), key=lambda i: str(qids[i])):
        rows = list(group)
        pool = pools[qid]
        assert len(pool) == len(rows) and np.array_equal(indexes[rows], np.arange(len(pool)))
        if len(pool) == 1 and pool[0].signals.get('exact'):
            extra.extend(np.zeros((1, 8)))
            manifest['exact_numeric_bypasses'] += 1
            continue
        assert saved[qid]['expanded_query'] == expanded[qid]
        source_rows = [owner_rows[c.entity][1] for c in pool]
        assert all(owner_rows[c.entity][0] == c.passages[0].source_hash for c in pool)
        selected = np.asarray(vectors[source_rows])
        a, b = [selected@query for query in queries[qid]]
        scored = [Candidate(c.entity, c.passages, {'cosine_code_original': float(x),
            'cosine_code_expanded': float(y)}, c.owned_regions) for c, x, y in zip(pool, a, b, strict=True)]
        value = contextual_features(scored)
        assert value.names == CONTEXTUAL_FEATURES
        extra.extend(value.values)
    matrix = np.column_stack((prefix, extra))
    assert matrix.shape == (len(qids), 259) and np.isfinite(matrix).all()
    np.savez_compressed(OUT/f'{repo}.npz', x=matrix, qid=qids, index=indexes)
    manifest['query_repos'][repo] = {'queries': len(set(qids)), 'rows': len(qids),
        'parent_features_sha256': sha(PARENT/f'{repo}.npz'), 'output_sha256': sha(OUT/f'{repo}.npz')}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'features_complete': repo, 'rows': len(qids)}), flush=True)
    del vectors, owner_rows, matrix, extra, prefix
    gc.collect()
assert manifest['exact_numeric_bypasses'] == 37
assert validate_replay_parent(PARENT, BASE) == bindings
assert len(validate_replay_parent(PARENT, BASE, extension=OUT)) == 68
assert verify_frozen_source(ENGINE) == receipt
assert sha(BASE/'registration.json') == manifest['source_registration_sha256']

for name, digest in original_model['artifacts'].items():
    assert sha(Path(original_model['root'])/name) == digest
for repo, root in roots.items():
    assert all(sha(root/path) == digest for path, digest in source_reg['source_repos'][repo]['file_hashes'].items())

manifest['complete'] = True
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
