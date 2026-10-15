"""Stream repository pools for the unchanged frozen code pair preference experiment."""
import gc
import hashlib
import json
import platform
import resource
import sqlite3
import sys
import time
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import ken
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from frozen_code_pairs import FrozenCodePairs
from pair_preferences import training_indices
from contextual_run import CPUContextEncoder
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/frozen-code-preference-features-v85b'
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
BASE = ROOT/'output/analysis/source7-context-views-ranking-v69'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
ASSETS = ROOT/'output/models/cpu-context-registration-v42.json'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
assets = json.loads(ASSETS.read_text())
asset_root = Path(assets['root'])
assert sha(ASSETS) == '9de3e49ef29ce4672b5b77dfca0078a4eba82412a64c318cafe048b512787d7a'
assert all(sha(asset_root/name) == digest for name, digest in assets['artifacts'].items())
assert sha(VIEWS/'registration.json') == 'd4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
source_reg = json.loads((VIEWS/'registration.json').read_text())
assert len(source_reg['source_repos']) == 16
assert sha(PARENT/'registration.json') == '74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
parent_receipt = json.loads((PARENT/'registration.json').read_text())
assert sha(POOL/'registration.json') == parent_receipt['public_inputs'][str(POOL/'registration.json')]
index_reg = json.loads((POOL/'registration.json').read_text())
assert sha(VIEWS/'model-registration.json') == source_reg['model_registration_sha256']
assert sha(ROOT/'output/models/cpu-context-registration-v42.json') == source_reg['original_model_registration_sha256']
roots = {name: Path(path) for name, path in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
# Rebind all complete source catalogs and physical files before reading requests.
source_bindings = {}
for repo, metadata in sorted(source_reg['source_repos'].items()):
    complete_files = index_reg['source_repos'][repo]['file_hashes']
    assert len(complete_files) == index_reg['source_repos'][repo]['indexed_files']
    assert str(metadata['source_generation']) == str(index_reg['source_repos'][repo]['generation'])
    assert all(sha(roots[repo]/path) == digest for path, digest in complete_files.items())
    paths = {VIEWS/(repo+'-source.db'): metadata['source_db_sha256'],
             VIEWS/(repo+'-vectors.npy'): metadata['vectors_sha256'],
             POOL/'context'/(repo+'.db'): metadata['base_full_context_sha256'],
             POOL/'indices'/(repo+'.db'): index_reg['source_repos'][repo]['new_source_index_sha256']}
    assert all(sha(path) == digest for path, digest in paths.items())
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['source_files'].items())
    source_bindings.update({str(path): digest for path, digest in paths.items()})
assert sum(len(item['file_hashes']) for item in index_reg['source_repos'].values()) == 6314
assert sha(PARENT/'registration.json') == '74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
bindings = validate_replay_parent(PARENT, POOL)
assert len(bindings) == 51
assert sha(BASE/'registration.json') == '9bb0d87b2f5306c7b3eee1a6484e271c6b3cfdb182fc3d408663bef6344fe814'
producer = json.loads((BASE/'registration.json').read_text())
assert sha(DATA) == producer['inputs'][str(DATA)] == '06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
scores_path = BASE/'contract_body251/scores.npy'
assert sha(scores_path) == 'c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3'
with np.load(DATA) as data:
    qids, repos = data['qid'], data['repo']
base_scores = np.load(scores_path)
assert base_scores.shape == qids.shape and np.isfinite(base_scores).all()
requests = {}
for path in sorted((POOL/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
with (POOL/'candidates.jsonl').open() as stream:
    saved = {row['id']: {'expanded_query': row['expanded_query']} for row in map(json.loads, stream)}
expanded_path = ROOT/'output/analysis/es-en-control-v16/queries.jsonl'
parent_reg = json.loads((PARENT/'registration.json').read_text())
assert sha(expanded_path) == parent_reg['public_inputs'][str(expanded_path)]
expanded = {row['id']: row['expanded'] for row in map(json.loads, expanded_path.read_text().splitlines())}
assert len(requests) == 400 and set(requests) == set(qids) == set(saved) == set(expanded)
case_rows = {qid: np.flatnonzero(qids == qid) for qid in requests}

context = CPUContextEncoder(assets)
pairs = FrozenCodePairs(context.session, context.tokenizer, query_prefix=context.query_prefix,
                        dimension=768, max_tokens=512)
policy = {'model_registration_sha256': sha(ASSETS), 'artifacts': assets['artifacts'],
    'query_prefix': context.query_prefix, 'tokenization': 'pair-query-prefix-and-unchanged69-implementation;no-padding;only_second512;batch1-v1',
    'projection': 'raw-CLS-float32,scaled-unit-float64,store-float32-v1',
    'provider': context.session.get_providers(), 'threads': [2, 1],
    'numpy': np.__version__, 'onnxruntime': ort.__version__, 'tokenizers': version('tokenizers'),
    'helper_sha256': sha(ENGINE/'experiments/search-engine/frozen_code_pairs.py')}
policy_id = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
manifest = {'scope': 'same frozen CPU CodeRank graph, no encoder fitting or extra model; sealed label-free evaluation first, then isolated potential training pairs',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-frozen-code-preference-v85b.md'),
    'pair_policy': policy, 'pair_policy_id': policy_id,
    'parent_bindings': bindings, 'source_bindings': source_bindings,
    'inputs': {str(path): sha(path) for path in (ASSETS, BASE/'registration.json', scores_path, DATA,
        expanded_path, VIEWS/'registration.json', ENGINE/'experiments/search-engine/pair_preferences.py')},
    'source_repos': source_reg['source_repos'], 'evaluation_queries': {}, 'training_queries': {},
    'indexed_source_repos': index_reg['source_repos'],
    'phases': {}, 'complete': False}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
cache = {}
encoded_new = 0
projection_ms = 0.


def packed(path, rows):
    np.savez_compressed(path, joint=np.stack([row['vector'] for row in rows]),
        qid=[row['id'] for row in rows], repo=[row['repo'] for row in rows],
        index=[row['index'] for row in rows], entity=[row['entity'] for row in rows],
        source_hash=[row['source_hash'] for row in rows], query_hash=[row['query_hash'] for row in rows],
        document_hash=[row['document_hash'] for row in rows], exact=[row['exact'] for row in rows])


for phase in ('evaluation', 'training'):
    phase_rows = []
    phase_new_before = encoded_new
    if phase == 'training':
        assert manifest['phases']['evaluation']['queries'] == 400
        assert sha(OUT/'evaluation-pairs.npz') == manifest['phases']['evaluation']['pairs_sha256']
        # Original eligibility is read only after ALL400 label-free prefixes are sealed.
        with np.load(DATA) as data:
            eligibility = data['y']
        assert eligibility.shape == qids.shape and np.isin(eligibility, (0, 1)).all()
    for repo, root in sorted(roots.items()):
        pools = load_pools(POOL, requests, repositories=[repo])
        assert set(pools) == {qid for qid, row in requests.items() if row['repo_id'] == repo}
        fold = next(item for item in producer['modes']['contract_body251']['folds'] if item['held_out'] == repo)
        assert set(fold['training_repos']) == set(roots)-{repo}
        db = sqlite3.connect(f'file:{VIEWS/(repo+"-source.db")}?mode=ro', uri=True)
        keys = {EntityKey(**json.loads(row[0])): row[0] for row in db.execute("SELECT entity FROM owners WHERE view='implementation'")}

        @lru_cache(maxsize=1024)
        def document(entity):
            digest, text_hash, text = db.execute('SELECT source_hash,o.text_hash,text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE entity=? AND view=?', (keys[entity], 'implementation')).fetchone()
            assert hashlib.sha256(text.encode()).hexdigest() == text_hash
            return digest, text_hash, text

        for qid in sorted(qid for qid, row in requests.items() if row['repo_id'] == repo):
            original_rows, pool = case_rows[qid], pools[qid]
            assert len(pool) == len(original_rows) and all(repos[original_rows] == repo)
            exact = bool(len(pool) == 1 and pool[0].signals.get('exact'))
            if phase == 'evaluation':
                order = sorted(range(len(pool)), key=lambda index: (-pool[index].signals.get('exact', 0), -base_scores[original_rows[index]], index))
                chosen = order[:20]
                metadata = {'repo': repo, 'indices': chosen, 'exact': exact}
            else:
                positive, negative = training_indices(eligibility[original_rows],
                    [item.signals.get('rrf', 0.) for item in pool], max_negatives=20)
                reason = 'exact_bypass' if exact else 'no_positive' if not len(positive) else 'no_negative' if not len(negative) else None
                chosen = [] if reason else [int(index) for index in np.concatenate((positive, negative))]
                metadata = {'repo': repo, 'positive_indices': positive.tolist(),
                    'negative_indices': negative.tolist(), 'indices': chosen, 'skip_reason': reason,
                    'priority': 'original-untrained-retrieval-rrf;not69scores'}
            assert len(chosen) == len(set(chosen))
            query = saved[qid]['expanded_query']
            query_hash = hashlib.sha256(query.encode()).hexdigest()
            if not exact:
                assert query == expanded[qid]
            for index in chosen:
                candidate = pool[index]
                if exact:
                    vector, text_hash = np.zeros(768, dtype=np.float32), ''
                else:
                    digest, text_hash, text = document(candidate.entity)
                    assert digest == candidate.passages[0].source_hash
                    key = (query_hash, text_hash, policy_id)
                    if key not in cache:
                        clock = time.perf_counter()
                        cache[key] = pairs.encode(query, [text])[0]
                        projection_ms += (time.perf_counter()-clock)*1000
                        encoded_new += 1
                    vector = cache[key]
                phase_rows.append({'id': qid, 'repo': repo, 'index': index, 'vector': vector,
                    'entity': keys[candidate.entity], 'source_hash': candidate.passages[0].source_hash,
                    'query_hash': query_hash, 'document_hash': text_hash, 'exact': exact})
            manifest[phase+'_queries'][qid] = metadata
        db.close()
        document.cache_clear()
        del keys, pools, pool, candidate
        gc.collect()
        print(json.dumps({'phase': phase, 'repo': repo, 'queries': len(manifest[phase+'_queries']),
            'assignment_rows': len(phase_rows), 'encoded_new_total': encoded_new,
            'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}), flush=True)
    destination = OUT/(phase+'-pairs.npz')
    packed(destination, phase_rows)
    manifest['phases'][phase] = {'queries': len(manifest[phase+'_queries']), 'rows': len(phase_rows),
        'pairs_sha256': sha(destination), 'encoded_new': encoded_new-phase_new_before}
    assert manifest['phases'][phase]['queries'] == 400
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    if phase == 'evaluation':
        sealed = {key: manifest[key] for key in ('pair_policy_id', 'evaluation_queries')}
        sealed['evaluation'] = manifest['phases']['evaluation']
        (OUT/'evaluation-seal.json').write_text(json.dumps(sealed, indent=2))
        manifest['evaluation_seal_sha256'] = sha(OUT/'evaluation-seal.json')
        print(json.dumps({'evaluation_phase_sealed': True, 'queries': 400,
            'pairs_sha256': manifest['phases']['evaluation']['pairs_sha256']}), flush=True)
    del phase_rows
assert sha(OUT/'evaluation-pairs.npz') == manifest['phases']['evaluation']['pairs_sha256']
assert sha(OUT/'evaluation-seal.json') == manifest['evaluation_seal_sha256']
assert bindings == validate_replay_parent(PARENT, POOL)
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert all(sha(path) == digest for path, digest in source_bindings.items())
assert all(sha(asset_root/name) == digest for name, digest in assets['artifacts'].items())
for repo, metadata in source_reg['source_repos'].items():
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['source_files'].items())
    assert all(sha(roots[repo]/path) == digest for path, digest in index_reg['source_repos'][repo]['file_hashes'].items())
assert verify_frozen_source(ENGINE) == receipt
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
manifest['encoded_new_total'] = encoded_new
manifest['pair_projection_ms'] = projection_ms
manifest['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
manifest['complete'] = True
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
