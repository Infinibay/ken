"""Frozen CPU pair logits, genuine source7 projections and ALL400 public pools."""
import argparse
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
import onnxruntime as ort
from tokenizers import Tokenizer
import ken

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.pair_relevance import PairRelevance
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import EntityKey

parser = argparse.ArgumentParser()
parser.add_argument('model', choices=('tiny', 'mini'))
args = parser.parse_args()
BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
SOURCE = ROOT/'output/analysis/context-views-source7-v69'
OUT = ROOT/f'output/analysis/marco-pair-features-v73-{args.model}'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
asset_file = ROOT/'output/models/marco-pair-registration-v73.json'
assets = json.loads(asset_file.read_text())[0 if args.model == 'tiny' else 1]
model_root = Path(assets['root'])
for name, digest in assets['artifacts'].items():
    assert sha(model_root/name) == digest
options = ort.SessionOptions()
options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
session = ort.InferenceSession(str(model_root/'onnx/model_qint8_arm64.onnx'),
    sess_options=options, providers=['CPUExecutionProvider'])
assert session.get_providers() == ['CPUExecutionProvider']
assert len(session.get_outputs()) == 1 and session.get_outputs()[0].shape[-1] == 1
tokenizer = Tokenizer.from_file(str(model_root/'tokenizer.json'))
judge = PairRelevance(session, tokenizer, max_tokens=512, batch_size=1)
source_reg = json.loads((SOURCE/'registration.json').read_text())
roots = {k: Path(v) for k, v in json.loads(
    (ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(source_reg['source_repos']) == len(roots) == 16
manifest = {'scope': 'ALL400 prepared pair logit control; source-only body projections first, '
    'no labels, no actualAPI/default/latency claim', 'model': assets,
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-marco-pair-control-v73.md'),
    'asset_registration_sha256': sha(asset_file),
    'source_registration_sha256': sha(SOURCE/'registration.json'),
    'pair_policy': {'max_tokens': 512, 'truncation': tokenizer.truncation,
        'batch_size': 1, 'threads': [2, 1], 'providers': session.get_providers(),
        'onnxruntime': ort.__version__, 'tokenizers': __import__('tokenizers').__version__,
        'projection': source_reg['projection'], 'view': 'implementation', 'output': 'raw-logit'},
    'source_repos': {}, 'query_repos': {}}
for repo, root in sorted(roots.items()):
    metadata = source_reg['source_repos'][repo]
    path = SOURCE/f'{repo}-source.db'
    assert sha(path) == metadata['source_db_sha256']
    for relative, digest in metadata['source_files'].items():
        assert sha(root/relative) == digest
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    rows = db.execute("SELECT entity,source_hash,o.text_hash,text FROM owners o "
        "JOIN texts t ON o.text_hash=t.text_hash WHERE view='implementation' ORDER BY entity").fetchall()
    assert len(rows) == metadata['owners']
    assert len({r[0] for r in rows}) == len(rows)
    assert all(hashlib.sha256(r[3].encode()).hexdigest() == r[2] for r in rows)
    manifest['source_repos'][repo] = {'owners': len(rows), 'source_files': metadata['source_files'],
        'source_generation': metadata['source_generation'], 'source_db_sha256': sha(path),
        'view_rows_sha256': hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest()}
    db.close()
    del rows
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
bindings = validate_replay_parent(PARENT, BASE)
parent_reg = json.loads((PARENT/'registration.json').read_text())
requests = {}
for path in sorted((BASE/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
assert len(requests) == 400
pools = load_pools(BASE, requests)
saved = {r['id']: r for r in map(json.loads, (BASE/'candidates.jsonl').read_text().splitlines())}
features = (*parent_reg['features'], *(f'marco_{args.model}_{q}_{stat}'
    for q in ('original', 'expanded') for stat in ('raw', 'to_max', 'range_relative', 'reciprocal_rank')))
assert len(features) == 259
manifest.update(features=features, parent_bindings=bindings,
    parent_features_registration_sha256=sha(PARENT/'registration.json'))
input_bindings = []
for repo in sorted(roots):
    db = sqlite3.connect(f'file:{SOURCE/(repo+"-source.db")}?mode=ro', uri=True)
    rows = db.execute("SELECT entity,source_hash,o.text_hash,text FROM owners o "
        "JOIN texts t ON o.text_hash=t.text_hash WHERE view='implementation' ORDER BY entity").fetchall()
    db.close()
    assert hashlib.sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest() == manifest['source_repos'][repo]['view_rows_sha256']
    owners = {EntityKey(**json.loads(e)): (digest, key, text) for e, digest, key, text in rows}
    del rows
    cache, calls, hits, timings, extras = {}, 0, 0, [], []
    with np.load(PARENT/f'{repo}.npz') as parent:
        for qid, indexes in itertools.groupby(range(len(parent['qid'])), key=lambda i: str(parent['qid'][i])):
            clock = time.perf_counter()
            indexes, pool = list(indexes), pools[qid]
            assert len(indexes) == len(pool)
            bypass = len(pool) == 1 and bool(pool[0].signals.get('exact'))
            columns, before_calls, before_hits = [], calls, hits
            for query_view, text in (('original', requests[qid]['request']['query']),
                                     ('expanded', saved[qid]['expanded_query'])):
                input_bindings.append({'id': qid, 'view': query_view,
                    'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'exact_numeric_bypass': bypass})
                if bypass:
                    continue
                logits = []
                for candidate in pool:
                    digest, key, document = owners[candidate.entity]
                    assert digest == candidate.passages[0].source_hash
                    pair = (text, key)
                    if pair not in cache:
                        cache[pair] = judge.score(text, [document], purpose='implementation')[0]
                        calls += 1
                    else:
                        hits += 1
                    logits.append(cache[pair])
                values = np.asarray(logits, dtype=np.float64)
                ranks = np.empty(len(values))
                ranks[np.argsort(-values, kind='stable')] = np.arange(1, len(values)+1)
                columns.extend((values, values-values.max(),
                    (values-values.min())/max(1e-9, float(np.ptp(values))), 1/ranks))
            extras.extend(np.zeros((1, 8)) if bypass else np.stack(columns, axis=1))
            timings.append({'id': qid, 'ms': (time.perf_counter()-clock)*1000,
                'new_pairs': calls-before_calls, 'cached_pairs': hits-before_hits, 'bypass': bypass})
        matrix = np.column_stack((parent['x'], extras))
        assert matrix.shape == (len(parent['qid']), 259) and np.isfinite(matrix).all()
        np.savez_compressed(OUT/f'{repo}.npz', x=matrix, qid=parent['qid'], index=parent['index'])
    (OUT/f'{repo}-pairs.jsonl').write_text(''.join(json.dumps({'query_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'document_hash': key, 'logit': value})+'\n' for (text, key), value in cache.items()))
    manifest['query_repos'][repo] = {'queries': 25, 'rows': len(matrix),
        'parent_features_sha256': sha(PARENT/f'{repo}.npz'), 'output_sha256': sha(OUT/f'{repo}.npz'),
        'pair_calls': calls, 'cached_pairs': hits, 'query_ms': timings,
        'pairs_sha256': sha(OUT/f'{repo}-pairs.jsonl'),
        'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'model': args.model, 'repo': repo, 'rows': len(matrix), 'pairs': calls}), flush=True)
    del owners, cache, matrix, extras
    gc.collect()
assert len(input_bindings) == 800 and len(manifest['query_repos']) == 16
(OUT/'query-input-bindings.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in input_bindings))
manifest['query_input_bindings_sha256'] = sha(OUT/'query-input-bindings.jsonl')
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
assert bindings == validate_replay_parent(PARENT, BASE)
assert sha(asset_file) == manifest['asset_registration_sha256']
assert sha(SOURCE/'registration.json') == manifest['source_registration_sha256']
assert verify_frozen_source(ENGINE) == receipt
