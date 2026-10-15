"""One pretrained int8 CPU comparator on an unchanged source69 top20 cascade."""
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
from ken.bench.pair_relevance import PairRelevance
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/jina-prefix-v84'
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
BASE = ROOT/'output/analysis/source7-context-views-ranking-v69'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
ASSETS = ROOT/'output/models/jina-pair-registration-v84.json'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
assets = json.loads(ASSETS.read_text())
asset_root = Path(assets['root'])
assert assets['license'] == 'apache-2.0' and len(assets['revision']) == 40
assert assets['protocol_sha256'] == sha(ENGINE/'experiments/search-engine/cpu-jina-prefix-v84.md')
assert all(sha(asset_root/name) == digest for name, digest in assets['artifacts'].items())
assert sha(VIEWS/'registration.json') == 'd4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
source_reg = json.loads((VIEWS/'registration.json').read_text())
assert len(source_reg['source_repos']) == 16
assert sha(VIEWS/'model-registration.json') == source_reg['model_registration_sha256']
assert sha(ROOT/'output/models/cpu-context-registration-v42.json') == source_reg['original_model_registration_sha256']
roots = {name: Path(path) for name, path in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
# Rebind all complete source catalogs and physical files before reading requests.
source_bindings = {}
for repo, metadata in sorted(source_reg['source_repos'].items()):
    paths = {VIEWS/(repo+'-source.db'): metadata['source_db_sha256'],
             VIEWS/(repo+'-vectors.npy'): metadata['vectors_sha256'],
             POOL/'context'/(repo+'.db'): metadata['base_full_context_sha256']}
    assert all(sha(path) == digest for path, digest in paths.items())
    assert all(sha(roots[repo]/path) == digest for path, digest in metadata['source_files'].items())
    source_bindings.update({str(path): digest for path, digest in paths.items()})
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
saved = {row['id']: row for row in map(json.loads, (POOL/'candidates.jsonl').read_text().splitlines())}
expanded_path = ROOT/'output/analysis/es-en-control-v16/queries.jsonl'
parent_reg = json.loads((PARENT/'registration.json').read_text())
assert sha(expanded_path) == parent_reg['public_inputs'][str(expanded_path)]
expanded = {row['id']: row['expanded'] for row in map(json.loads, expanded_path.read_text().splitlines())}
assert len(requests) == 400 and set(requests) == set(qids) == set(saved) == set(expanded)
pools = load_pools(POOL, requests)
case_rows = {qid: np.flatnonzero(qids == qid) for qid in requests}
options = ort.SessionOptions()
options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
session = ort.InferenceSession(str(asset_root/'onnx/model_int8.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
assert session.get_providers() == ['CPUExecutionProvider']
assert {item.name for item in session.get_inputs()} <= {'input_ids', 'attention_mask', 'token_type_ids'}
assert {'input_ids', 'attention_mask'} <= {item.name for item in session.get_inputs()}
tok = Tokenizer.from_file(str(asset_root/'tokenizer.json'))
tok.no_padding()
judge = PairRelevance(session, tok, max_tokens=512, batch_size=1)
synthetic = judge.score('Which planet is red?', ['Mars is known as the red planet.', 'An oak tree grows leaves.'], purpose='implementation')
assert len(synthetic) == 2 and np.isfinite(synthetic).all()
manifest = {'scope': 'ALL400 prepared source69 prefix20; one official compact int8 CPU pair model, same original criteria; no new fit/API/default/private claim',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-jina-prefix-v84.md'),
    'assets': assets, 'provider': session.get_providers(),
    'runtime': {'python': sys.version, 'platform': platform.platform(), 'numpy': np.__version__,
        'onnxruntime': ort.__version__, 'tokenizers': version('tokenizers')},
    'input_shapes': {item.name: item.shape for item in session.get_inputs()},
    'output_shapes': {item.name: item.shape for item in session.get_outputs()},
    'synthetic_logits': synthetic, 'parent_bindings': bindings, 'source_bindings': source_bindings,
    'inputs': {str(path): sha(path) for path in (ASSETS, BASE/'registration.json', scores_path, DATA, expanded_path, VIEWS/'registration.json')},
    'parameters': {'prefix': 20, 'batch_size': 1, 'threads': [2, 1], 'max_tokens': 512, 'padding': None,
        'truncation': 'only_second', 'tie': 'source69rank', 'readouts': ['raw', 'equal_rrf60']},
    'results': {}, 'timings': [], 'selected': []}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
responses = {name: [] for name in ('baseline', 'raw', 'equal_rrf60')}
folds = {fold['held_out']: fold for fold in producer['modes']['contract_body251']['folds']}
for repo, root in sorted(roots.items()):
    assert set(folds[repo]['training_repos']) == set(roots)-{repo}
    model = NumericRanker.from_dict(json.loads((BASE/'contract_body251'/(repo+'-numeric.json')).read_text()))
    assert model.fingerprint == folds[repo]['model_fingerprint']
    db = sqlite3.connect(f'file:{VIEWS/(repo+"-source.db")}?mode=ro', uri=True)
    keys = {EntityKey(**json.loads(row[0])): row[0] for row in db.execute("SELECT entity FROM owners WHERE view='implementation'")}

    @lru_cache(maxsize=1024)
    def document(entity):
        digest, text_hash, text = db.execute('SELECT source_hash,o.text_hash,text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE entity=? AND view=?', (keys[entity], 'implementation')).fetchone()
        assert hashlib.sha256(text.encode()).hexdigest() == text_hash
        return digest, text_hash, text

    for qid in sorted(qid for qid, row in requests.items() if row['repo_id'] == repo):
        rows, pool = case_rows[qid], pools[qid]
        assert len(pool) == len(rows) and all(repos[rows] == repo)
        base_order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0), -base_scores[rows[i]], i))
        prefix = base_order[:20]
        exact = len(pool) == 1 and pool[0].signals.get('exact')
        docs, doc_hashes = [], []
        if not exact:
            assert saved[qid]['expanded_query'] == expanded[qid]
            for index in prefix:
                digest, text_hash, text = document(pool[index].entity)
                assert digest == pool[index].passages[0].source_hash
                docs.append(text)
                doc_hashes.append(text_hash)
        clock = time.perf_counter()
        logits = np.zeros(len(prefix)) if exact else np.asarray(judge.score(saved[qid]['expanded_query'], docs, purpose='implementation'))
        elapsed = (time.perf_counter()-clock)*1000
        assert logits.shape == (len(prefix),) and np.isfinite(logits).all()
        pair_order = sorted(range(len(prefix)), key=lambda i: (-logits[i], i))
        pair_ranks = {index: rank for rank, index in enumerate(pair_order, 1)}
        fused = np.array([1./(60+i+1)+1./(60+pair_ranks[i]) for i in range(len(prefix))])
        manifest['timings'].append({'id': qid, 'pairs': 0 if exact else len(prefix), 'pair_ms': elapsed})
        manifest['selected'].append({'id': qid, 'indices': prefix, 'query_sha256': hashlib.sha256(saved[qid]['expanded_query'].encode()).hexdigest(),
            'doc_hashes': doc_hashes, 'logits': logits.tolist(), 'exact_bypass': bool(exact)})
        for mode, added in (('baseline', None), ('raw', logits), ('equal_rrf60', fused)):
            if added is None:
                order, visible = base_order, {}
                profile = model.fingerprint
            else:
                positions = sorted(range(len(prefix)), key=lambda i: (-pool[prefix[i]].signals.get('exact', 0), -added[i], i))
                order = [prefix[i] for i in positions]+base_order[20:]
                assert order[20:] == base_order[20:] and set(order[:len(prefix)]) == set(prefix)
                visible = {index: float(score) for index, score in zip(prefix, added, strict=True)}
                profile = hashlib.sha256(json.dumps({'engine': receipt, 'graph': assets['artifacts']['onnx/model_int8.onnx'],
                    'source_ranker': model.fingerprint, 'mode': mode, 'policy': 'source69prefix20-evidence3-512-only_second-v1'}, sort_keys=True).encode()).hexdigest()
            assert len(order) == len(set(order)) == len(pool)
            matches = [CodeMatch(pool[i].entity, visible.get(i, float(base_scores[rows[i]])), pool[i].passages,
                pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
            request = SearchRequest(**requests[qid]['request'])
            matches = complete_evidence(matches, root, request)
            responses[mode].append({'id': qid, **present(matches, root, request, profile_version=profile).to_dict()})
    db.close()
    document.cache_clear()
    del keys
    gc.collect()
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'repo': repo, 'completed': len(responses['raw'])}), flush=True)
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert all(sha(path) == digest for path, digest in source_bindings.items())
assert all(sha(asset_root/name) == digest for name, digest in assets['artifacts'].items())
assert bindings == validate_replay_parent(PARENT, POOL)
assert verify_frozen_source(ENGINE) == receipt
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
from ken.bench.retrieval import evaluate
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
for mode, values in responses.items():
    assert len(values) == len({row['id'] for row in values}) == 400
    report = evaluate(cases, values, roots=roots)
    if mode == 'baseline':
        assert report['strict_top1'] == {'hits': 286, 'total': 400, 'rate': .715}
        assert report['identity_top1'] == {'hits': 298, 'total': 400, 'rate': .745}
    (OUT/(mode+'-responses.jsonl')).write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in values))
    (OUT/(mode+'-report.json')).write_text(json.dumps(report, indent=2))
    manifest['results'][mode] = {'strict': report['strict_top1'], 'identity': report['identity_top1'], 'missing': report['missing_response_ids']}
    print(json.dumps({'mode': mode, **manifest['results'][mode]}), flush=True)
manifest['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
manifest['heavy_runtimes_imported'] = []
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
