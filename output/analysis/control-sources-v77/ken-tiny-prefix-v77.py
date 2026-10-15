"""Same fixed tiny models; live CPU rerank only the fixed source69 top20 owners."""
import gc
import hashlib
import json
import resource
import sqlite3
import sys
import time
from functools import lru_cache
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
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/tiny-prefix-v77'
TRAINED = ROOT/'output/analysis/tiny-domain-training-v75c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
TEACHER = ROOT/'output/analysis/marco-pair-features-v73-tiny'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
BASE = ROOT/'output/analysis/source7-context-views-ranking-v69'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
ASSETS = ROOT/'output/models/marco-tiny-native-registration-v75.json'
OUT.mkdir(exist_ok=False)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(ENGINE)
while True:
    try:
        trained_reg = json.loads((TRAINED/'registration.json').read_text())
        if len(trained_reg['folds']) == 16 and len(trained_reg['results']) == 4:
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
assert trained_reg['engine_receipt'] == verify_frozen_source(ROOT/'output/frozen/cpu-tiny-domain-training-v75c') == '738c30d9b51155fccbff0f4c9fb9709e4a1c2da4822b543edd4444c1a0eb9873'
assert sha('/private/tmp/ken-tiny-domain-training-v75c.py') == trained_reg['script_sha256']
for key in ('inputs', 'expected_inputs', 'producer_receipts', 'pretrained_cache_bindings'):
    assert all(sha(path) == digest for path, digest in trained_reg[key].items())
bindings = validate_replay_parent(PARENT, POOL, extension=TEACHER)
assert bindings == trained_reg['parent_bindings'] and len(bindings) == 68
assert sha(DATA) == '06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
base_path = BASE/'contract_body251/scores.npy'
assert sha(base_path) == 'c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3'
with np.load(DATA) as data:
    qids, repos = data['qid'], data['repo']
base_scores = np.load(base_path)
assert base_scores.shape == qids.shape
requests = {}
for path in sorted((POOL/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
saved = {row['id']: row for row in map(json.loads, (POOL/'candidates.jsonl').read_text().splitlines())}
pools = load_pools(POOL, requests)
roots = {k: Path(v) for k, v in json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
assert len(requests) == 400 and len(roots) == 16 and set(requests) == set(qids)
case_rows = {qid: np.flatnonzero(qids == qid) for qid in requests}
source_reg = json.loads((VIEWS/'registration.json').read_text())
assets = json.loads(ASSETS.read_text())
model_root = Path(assets['root'])
assert assets == trained_reg['assets']
assert all(sha(model_root/name) == digest for name, digest in assets['artifacts'].items())
manifest = {'scope': 'ALL400 prepared upstream ranking69;fixed20 reranking live CPU using same75c models, no newfit/queryfilter/API/default/private claim',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-tiny-prefix-v77.md'),
    'parent_bindings': bindings, 'parameters': {'prefix': 20, 'batch_size': 1, 'threads': [2, 1], 'max_tokens': 512, 'truncation': 'only_second', 'tie': 'source69rank'},
    'inputs': {str(p): sha(p) for p in (TRAINED/'registration.json', TRAINED/'pretrained-scores.npy',
        TRAINED/'adapted-scores.npy', DATA, base_path, VIEWS/'registration.json', ASSETS)},
    'graphs': {}, 'results': {}, 'timings': {}}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))


def judge_for(folder, expected):
    record = json.loads((folder/'export.json').read_text())
    assert record == expected and sha(folder/'model.onnx') == record['graph_sha256']
    assert sha(folder/'native/model.safetensors') == record['native_sha256']
    manifest['graphs'][str(folder/'model.onnx')] = record['graph_sha256']
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    session = ort.InferenceSession(str(folder/'model.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
    assert session.get_providers() == ['CPUExecutionProvider']
    tok = Tokenizer.from_file(str(model_root/'tokenizer.json'))
    tok.enable_truncation(max_length=512, strategy='only_second')
    return PairRelevance(session, tok, max_tokens=512, batch_size=1)


all_responses = {}
for mode in ('pretrained', 'adapted'):
    stored = np.load(TRAINED/f'{mode}-scores.npy')
    assert stored.shape == qids.shape and np.isfinite(stored).all()
    responses, timings = [], []
    for repo, root in sorted(roots.items()):
        if mode == 'adapted':
            fold = next(f for f in trained_reg['folds'] if f['held_out'] == repo)
            assert set(fold['training_repos']) == set(roots)-{repo}
            folder, record = TRAINED/repo/'final', fold['export']
        else:
            folder, record = TRAINED/'pretrained', trained_reg['pretrained_export']
        judge = judge_for(folder, record)
        metadata = source_reg['source_repos'][repo]
        assert sha(VIEWS/f'{repo}-source.db') == metadata['source_db_sha256']
        assert all(sha(root/path) == digest for path, digest in metadata['source_files'].items())
        db = sqlite3.connect(f'file:{VIEWS/(repo+"-source.db")}?mode=ro', uri=True)
        keys = {EntityKey(**json.loads(row[0])): row[0] for row in db.execute("SELECT entity FROM owners WHERE view='implementation'")}

        @lru_cache(maxsize=1024)
        def document(entity):
            digest, text_hash, text = db.execute('SELECT source_hash,o.text_hash,text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE entity=? AND view=?', (keys[entity], 'implementation')).fetchone()
            assert hashlib.sha256(text.encode()).hexdigest() == text_hash
            return digest, text

        for qid in sorted(qid for qid, row in requests.items() if row['repo_id'] == repo):
            rows, pool = case_rows[qid], pools[qid]
            assert len(pool) == len(rows) and all(repos[rows] == repo)
            base_order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0), -base_scores[rows[i]], i))
            prefix = base_order[:20]
            clock = time.perf_counter()
            exact = len(pool) == 1 and pool[0].signals.get('exact')
            if exact:
                logits = np.zeros(1)
            else:
                docs = []
                for index in prefix:
                    source_hash, text = document(pool[index].entity)
                    assert source_hash == pool[index].passages[0].source_hash
                    docs.append(text)
                logits = judge.score(saved[qid]['expanded_query'], docs, purpose='implementation')
            assert np.array_equal(logits, stored[rows[prefix]])
            elapsed = (time.perf_counter()-clock)*1000
            sorted_positions = sorted(range(len(prefix)), key=lambda i: (-pool[prefix[i]].signals.get('exact', 0), -logits[i], i))
            reordered = [prefix[i] for i in sorted_positions]
            order = reordered+base_order[20:]
            assert set(reordered) == set(prefix) and order[20:] == base_order[20:]
            assert len(order) == len(set(order)) == len(pool)
            # Ranking is lexicographic(stage69prefix, tinylogit, stage69tie).
            # Scores expose the tiny logit in the only visible prefix; tail retains base scores.
            visible_scores = {index: float(logit) for index, logit in zip(prefix, logits, strict=True)}
            matches = [CodeMatch(pool[i].entity, visible_scores.get(i, float(base_scores[rows[i]])),
                pool[i].passages, pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
            request = SearchRequest(**requests[qid]['request'])
            matches = complete_evidence(matches, root, request)
            responses.append({'id': qid, **present(matches, root, request,
                profile_version=hashlib.sha256((receipt+mode+repo).encode()).hexdigest()).to_dict()})
            timings.append({'id': qid, 'pairs': 0 if exact else len(prefix), 'pair_ms': elapsed})
        db.close()
        document.cache_clear()
        del judge, keys
        gc.collect()
    assert len(responses) == len({r['id'] for r in responses}) == 400
    all_responses[mode] = responses
    manifest['timings'][mode] = timings
    (OUT/f'{mode}-responses.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in responses))
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert all(sha(path) == digest for path, digest in manifest['graphs'].items())
assert validate_replay_parent(PARENT, POOL, extension=TEACHER) == bindings
assert verify_frozen_source(ENGINE) == receipt
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
from ken.bench.retrieval import evaluate
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
for mode, responses in all_responses.items():
    report = evaluate(cases, responses, roots=roots)
    (OUT/f'{mode}-report.json').write_text(json.dumps(report, indent=2))
    manifest['results'][mode] = {'strict': report['strict_top1'], 'identity': report['identity_top1'], 'missing': report['missing_response_ids']}
    print(json.dumps({'mode': mode, **manifest['results'][mode]}), flush=True)
manifest['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
manifest['heavy_runtimes_imported'] = sorted(name for name in ('torch', 'transformers', 'sentence_transformers') if name in sys.modules)
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
