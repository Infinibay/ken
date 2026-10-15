"""Fixed CPU4.4M domain adaptation, whole-repository exclusion and strict replay."""
import gc
import hashlib
import json
import math
import random
import resource
import shutil
import sqlite3
import sys
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from tokenizers import Tokenizer
from transformers import BertForSequenceClassification
from safetensors.torch import load_file
import ken

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from pair_training import training_groups
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.pair_relevance import PairRelevance
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest
from ken.retrieval.presentation import present

OUT = ROOT/'output/analysis/tiny-domain-training-v75c'
OUT.mkdir(exist_ok=False)
POOL = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
TEACHER = ROOT/'output/analysis/marco-pair-features-v73-tiny'
DATA = ROOT/'output/analysis/source7-ranking-v66c/training-matrix.npz'
BASE = ROOT/'output/analysis/source7-context-views-ranking-v69'
ASSETS = ROOT/'output/models/marco-tiny-native-registration-v75.json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# Expected producer receipts are fixed before training or quality inspection.
PRODUCERS = {
    ROOT/'output/analysis/source7-ranking-v66c/registration.json':
        'dec0d03e5e01f33c467218f410013d07792e4aca0599f8c707bef1933e60b16d',
    BASE/'registration.json':
        '9bb0d87b2f5306c7b3eee1a6484e271c6b3cfdb182fc3d408663bef6344fe814',
    ROOT/'output/analysis/complete-owned-context-v72c/registration.json':
        '70f9c8bee6081049712dabc29da2ddeda63ae4a70211b100a4d355f0bbdd7c6a',
}
EXPECTED = {
    DATA: '06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff',
    BASE/'contract_body251/scores.npy':
        'c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3',
}
CACHE = ROOT/'output/analysis/tiny-domain-training-v75'
CACHE_EXPECTED = {
    CACHE/'registration.json': '1a4ce9ba7f1c0e0a5474fd6279736d256e3f65b957d5436c4b5baf7120f33e0a',
    CACHE/'pretrained-scores.npy': '64ec333a0785a6607dbf4b458f44f60cf2bc381644f426cb58336b54fca5a85a',
    CACHE/'pretrained/export.json': 'd6b30061e1d0daffa399e8bd37d0251fdb4b97634de48bcf5eaf42b5916709dc',
}
for path, digest in (PRODUCERS | EXPECTED | CACHE_EXPECTED).items():
    assert sha(path) == digest, f'expected producer/input bytes differ: {path}'
producer66, producer69, producer72 = [json.loads(p.read_text()) for p in PRODUCERS]
assert producer66['inputs'][str(DATA)] == producer69['inputs'][str(DATA)] == EXPECTED[DATA]
score_path = BASE/'contract_body251/scores.npy'
assert producer72['inputs'][str(score_path)] == EXPECTED[score_path]
cache_manifest = json.loads((CACHE/'registration.json').read_text())
assert cache_manifest['folds'] == [] and cache_manifest['results'] == {}
assert len(cache_manifest['pretrained_timings']) == 400
old_engine = ROOT/'output/frozen/cpu-tiny-domain-training-v75'
assert verify_frozen_source(old_engine) == cache_manifest['engine_receipt'] == \
    '0dfe2244049efcc940f5c5ede74dc8ddfd87db6b46258c7e38b369abea493a4c'
assert sha('/private/tmp/ken-tiny-domain-training-v75.py') == cache_manifest['script_sha256']
for path, digest in cache_manifest['inputs'].items():
    assert sha(path) == digest, f'pretrained input changed: {path}'
receipt = verify_frozen_source(ENGINE)
bindings = validate_replay_parent(PARENT, POOL, extension=TEACHER)
assert len(bindings) == 68
assets = json.loads(ASSETS.read_text())
model_root = Path(assets['root'])
for name, digest in assets['artifacts'].items():
    assert sha(model_root/name) == digest
roots = {k: Path(v) for k, v in json.loads(
    (ROOT/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
requests = {}
for path in sorted((POOL/'requests').glob('*.jsonl')):
    for row in map(json.loads, path.read_text().splitlines()):
        assert row['id'] not in requests
        requests[row['id']] = row
assert len(requests) == 400 and len(roots) == 16
saved = {r['id']: r for r in map(json.loads, (POOL/'candidates.jsonl').read_text().splitlines())}
pools = load_pools(POOL, requests)
data = np.load(DATA)
qids, repos, labels = data['qid'], data['repo'], data['y']
assert len(qids) == len(repos) == len(labels) == 167360
assert set(qids) == set(requests) == set(saved)
indexes, teacher_values = np.empty(len(qids), dtype=np.int64), np.empty(len(qids))
for repo in sorted(roots):
    selected = np.flatnonzero(repos == repo)
    with np.load(TEACHER/f'{repo}.npz') as teacher:
        assert np.array_equal(teacher['qid'], qids[selected])
        indexes[selected], teacher_values[selected] = teacher['index'], teacher['x'][:, 255]
assert json.loads((TEACHER/'registration.json').read_text())['features'][255] == 'marco_tiny_expanded_raw'
base_scores = np.load(BASE/'contract_body251/scores.npy')
assert base_scores.shape == qids.shape
exact_ids = {qid for qid, pool in pools.items() if len(pool) == 1 and pool[0].signals.get('exact')}
assert len(exact_ids) == 37
case_rows = {qid: np.flatnonzero(qids == qid) for qid in requests}
source_reg = json.loads((VIEWS/'registration.json').read_text())
dbs, entity_strings = {}, {}
for repo, root in sorted(roots.items()):
    metadata = source_reg['source_repos'][repo]
    assert sha(VIEWS/f'{repo}-source.db') == metadata['source_db_sha256']
    for path, digest in metadata['source_files'].items():
        assert sha(root/path) == digest
    db = sqlite3.connect(f'file:{VIEWS/(repo+"-source.db")}?mode=ro', uri=True)
    entities = db.execute("SELECT entity FROM owners WHERE view='implementation' ORDER BY entity").fetchall()
    entity_strings[repo] = {EntityKey(**json.loads(e[0])): e[0] for e in entities}
    assert len(entity_strings[repo]) == metadata['owners']
    dbs[repo] = db


@lru_cache(maxsize=4096)
def document(repo, entity):
    digest, key, text = dbs[repo].execute(
        "SELECT source_hash,o.text_hash,text FROM owners o JOIN texts t "
        "ON o.text_hash=t.text_hash WHERE entity=? AND view='implementation'",
        (entity_strings[repo][entity],)).fetchone()
    assert hashlib.sha256(text.encode()).hexdigest() == key
    return digest, text


def row_document(row):
    qid = str(qids[row])
    candidate = pools[qid][int(indexes[row])]
    digest, text = document(requests[qid]['repo_id'], candidate.entity)
    assert digest == candidate.passages[0].source_hash
    return text


torch.set_num_threads(2)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
torch.manual_seed(20261015)
manifest = {'scope': 'ALL400 source7 prepared CPU4.4M adaptation;16fresh pretrained resets; '
    'whole held repo excluded; no API/default/private/resource certificate',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'protocol_sha256': sha(ENGINE/'experiments/search-engine/cpu-tiny-domain-training-v75c.md'),
    'expected_inputs': {str(p): digest for p, digest in EXPECTED.items()},
    'producer_receipts': {str(p): digest for p, digest in PRODUCERS.items()},
    'pretrained_cache_bindings': {str(p): digest for p, digest in CACHE_EXPECTED.items()},
    'assets': assets, 'inputs': {str(p): sha(p) for p in (
        ASSETS, DATA, BASE/'registration.json', BASE/'contract_body251/scores.npy',
        VIEWS/'registration.json', TEACHER/'registration.json', POOL/'candidates.jsonl')},
    'parent_bindings': bindings, 'parameters': {'epochs': 3, 'lr': 2e-5,
        'weight_decay': .01, 'query_accumulation': 4, 'max_negative': 4,
        'max_tokens': 512, 'seed': 20261015, 'warmup_fraction': .1, 'clip_norm': 1.,
        'torch': torch.__version__, 'transformers': __import__('transformers').__version__,
        'onnxruntime': ort.__version__, 'cpu_threads': [2, 1], 'dtype': 'float32'},
    'folds': [], 'results': {}}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))


def fresh_model():
    torch.manual_seed(20261015)
    assert sha(model_root/'model.safetensors') == assets['artifacts']['model.safetensors']
    model = BertForSequenceClassification.from_pretrained(model_root, local_files_only=True,
        trust_remote_code=False, use_safetensors=True, attn_implementation='eager').to('cpu')
    assert sum(p.numel() for p in model.parameters()) == 4386049
    assert all(p.device.type == 'cpu' and p.dtype == torch.float32 for p in model.parameters())
    return model


def tokenizer(padding=False):
    result = Tokenizer.from_file(str(model_root/'tokenizer.json'))
    result.enable_truncation(max_length=512, strategy='only_second')
    if padding:
        result.enable_padding(pad_id=0, pad_token='[PAD]')
    return result


def encode(tok, query, docs):
    encoded = tok.encode_batch([(query, d) for d in docs])
    return {name: torch.tensor([getattr(e, attr) for e in encoded], dtype=torch.long)
        for name, attr in (('input_ids', 'ids'), ('attention_mask', 'attention_mask'),
                           ('token_type_ids', 'type_ids'))}


class Pair(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model
    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.model(input_ids=input_ids, attention_mask=attention_mask,
                          token_type_ids=token_type_ids).logits


def exported(model, folder):
    folder.mkdir(exist_ok=False)
    model.eval()
    model.save_pretrained(folder/'native', safe_serialization=True)
    tok = tokenizer()
    features = encode(tok, 'validate before storing', ['def store(x): validate(x); save(x)'])
    names = ('input_ids', 'attention_mask', 'token_type_ids')
    graph = folder/'model.onnx'
    with torch.inference_mode():
        torch.onnx.export(Pair(model).eval(), tuple(features[n] for n in names), str(graph),
            input_names=list(names), output_names=['logits'],
            dynamic_axes={n: {0: 'batch', 1: 'sequence'} for n in names}|{'logits': {0: 'batch'}},
            opset_version=17, dynamo=False)
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    session = ort.InferenceSession(str(graph), sess_options=options, providers=['CPUExecutionProvider'])
    assert session.get_providers() == ['CPUExecutionProvider']
    probes = []
    for query, text in (('', ''), ('preserve Owner.method', 'def Owner_method(x): return x'),
        ('validar y guardar', 'def store(x): validate(x); save(x)'),
        ('normalize naïve Δ', 'def normalize(naïve): return naïve.lower()'),
        ('keep constraints at the end', 'def large(x):\n'+'    step(x)\n'*200)):
        values = encode(tok, query, [text])
        with torch.inference_mode():
            expected = model(**values).logits.numpy()
        actual = session.run(None, {n: v.numpy() for n, v in values.items()})[0]
        delta = float(np.max(np.abs(actual-expected)))
        assert delta <= 2e-5 and np.isfinite(actual).all()
        probes.append({'query_sha256': hashlib.sha256(query.encode()).hexdigest(),
            'document_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'tokens': values['input_ids'].shape[1], 'max_abs_delta': delta})
    record = {'graph_sha256': sha(graph), 'graph_bytes': graph.stat().st_size,
        'native_sha256': sha(folder/'native/model.safetensors'), 'probes': probes}
    (folder/'export.json').write_text(json.dumps(record, indent=2))
    return PairRelevance(session, tok, max_tokens=512, batch_size=1), record


def predict(judge, selected_qids, output):
    timings = []
    for qid in selected_qids:
        rows = case_rows[qid]
        clock = time.perf_counter()
        if qid in exact_ids:
            output[rows] = 0.
        else:
            output[rows] = judge.score(saved[qid]['expanded_query'],
                [row_document(int(row)) for row in rows], purpose='implementation')
        timings.append({'id': qid, 'pairs': 0 if qid in exact_ids else len(rows),
                        'ms': (time.perf_counter()-clock)*1000})
    return timings


# Reuse only the completed, independently reviewed, untrained float32 parent.
# Labels were never used to produce these scores; no fold in75 was trained.
pretrained = np.load(CACHE/'pretrained-scores.npy')
adapted = np.full(len(qids), np.nan)
assert pretrained.shape == qids.shape and np.isfinite(pretrained).all()
assert {row['id'] for row in cache_manifest['pretrained_timings']} == set(requests)
assert cache_manifest['assets'] == assets and cache_manifest['parent_bindings'] == bindings
assert cache_manifest['parameters'] == manifest['parameters']
for name in ('src/ken/retrieval/evidence.py', 'src/ken/retrieval/presentation.py',
             'src/ken/retrieval/result_selection.py', 'src/ken/bench/pair_relevance.py'):
    assert sha(ENGINE/name) == sha(old_engine/name)
export = json.loads((CACHE/'pretrained/export.json').read_text())
assert sha(CACHE/'pretrained/model.onnx') == export['graph_sha256']
assert sha(CACHE/'pretrained/native/model.safetensors') == export['native_sha256']
assert export == cache_manifest['pretrained_export']
official = load_file(model_root/'model.safetensors', device='cpu')
cached = load_file(CACHE/'pretrained/native/model.safetensors', device='cpu')
# Transformers4.57 saves only persistent tensors. The original checkpoint also
# contains the canonical position_ids buffer, generated unchanged by BertEmbeddings.
position_ids = official.pop('bert.embeddings.position_ids')
assert torch.equal(position_ids, torch.arange(512, dtype=torch.long).reshape(1, 512))
assert official.keys() == cached.keys()
assert all(torch.equal(official[key], cached[key]) for key in official)
del official, cached
options = ort.SessionOptions()
options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
session = ort.InferenceSession(str(CACHE/'pretrained/model.onnx'), sess_options=options,
                              providers=['CPUExecutionProvider'])
assert session.get_providers() == ['CPUExecutionProvider']
judge = PairRelevance(session, tokenizer(), max_tokens=512, batch_size=1)
cache_probes = []
for repo in sorted(roots):
    # Selection uses only source identity, never a label, logit, rank, or reference.
    qid = min(qid for qid, request in requests.items()
              if request['repo_id'] == repo and qid not in exact_ids)
    row = int(case_rows[qid][0])
    actual = judge.score(saved[qid]['expanded_query'], [row_document(row)],
                         purpose='implementation')[0]
    assert actual == pretrained[row]
    cache_probes.append({'repo': repo, 'id': qid, 'row': row,
        'query_sha256': hashlib.sha256(saved[qid]['expanded_query'].encode()).hexdigest(),
        'document_sha256': hashlib.sha256(row_document(row).encode()).hexdigest(),
        'max_abs_delta': float(abs(actual-pretrained[row]))})
shutil.copytree(CACHE/'pretrained', OUT/'pretrained')
shutil.copy2(CACHE/'pretrained-scores.npy', OUT/'pretrained-scores.npy')
assert sha(OUT/'pretrained-scores.npy') == CACHE_EXPECTED[CACHE/'pretrained-scores.npy']
assert sha(OUT/'pretrained/model.onnx') == export['graph_sha256']
del judge, session
gc.collect()
manifest['pretrained_export'] = export
manifest['pretrained_timings'] = cache_manifest['pretrained_timings']
manifest['pretrained_cache_probes'] = cache_probes
manifest['pretrained_cache_source'] = str(CACHE)
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps({'pretrained_verified': 400, 'cache_probes': len(cache_probes)}), flush=True)
# An explicit pause after all input/cache checks allows independent pre-fit review.
print(json.dumps({'awaiting_prefit_review': True}), flush=True)
while not (OUT/'PRE-FIT-REVIEW-ACCEPTED.json').is_file():
    time.sleep(2)
for path, digest in (PRODUCERS | EXPECTED | CACHE_EXPECTED).items():
    assert sha(path) == digest
for held in sorted(roots):
    started = time.perf_counter()
    groups = training_groups(qids=qids, repos=repos, labels=labels, indexes=indexes,
        pair_scores=teacher_values, held_out=held, exact_ids=exact_ids)
    assert groups and all(g.repo != held for g in groups)
    assert {g.repo for g in groups} == set(roots)-{held}
    folder = OUT/held
    folder.mkdir(exist_ok=False)
    group_file = folder/'training-groups.json'
    group_file.write_text(json.dumps([asdict(g) for g in groups], indent=2))
    model = fresh_model()
    model.train()
    tok = tokenizer(padding=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=.01,
                                  foreach=False, fused=False)
    total_steps = 3*math.ceil(len(groups)/4)
    warmup = max(1, int(total_steps*.1))
    losses, step = [], 0
    for epoch in range(3):
        shuffled = list(groups)
        random.Random(20261015+epoch).shuffle(shuffled)
        epoch_loss = 0.
        for start in range(0, len(shuffled), 4):
            batch = shuffled[start:start+4]
            optimizer.zero_grad(set_to_none=True)
            for group in batch:
                values = encode(tok, saved[group.qid]['expanded_query'],
                    [row_document(i) for i in (group.positive, *group.negatives)])
                logits = model(**values).logits.reshape(1, -1)
                loss = torch.nn.functional.cross_entropy(logits, torch.zeros(1, dtype=torch.long))
                assert torch.isfinite(loss)
                (loss/len(batch)).backward()
                epoch_loss += float(loss.detach())
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.)
            rate = 2e-5*((step+1)/warmup if step < warmup else
                         (total_steps-step)/max(1, total_steps-warmup))
            for param in optimizer.param_groups:
                param['lr'] = rate
            optimizer.step()
            step += 1
        losses.append(epoch_loss/len(groups))
        print(json.dumps({'held': held, 'epoch': epoch+1, 'training_queries': len(groups),
                          'training_loss': losses[-1]}), flush=True)
    assert step == total_steps
    del optimizer
    judge, export = exported(model, folder/'final')
    del model, values, logits, loss
    timings = predict(judge, [qid for qid, r in requests.items() if r['repo_id'] == held], adapted)
    del judge
    np.save(OUT/'adapted-scores.npy', adapted)
    manifest['folds'].append({'held_out': held, 'training_repos': sorted(set(roots)-{held}),
        'training_queries': len(groups), 'training_groups_sha256': sha(group_file),
        'steps': total_steps, 'losses': losses, 'export': export, 'prediction_ms': timings,
        'ms': (time.perf_counter()-started)*1000,
        'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'fold_complete': held, 'completed': np.isfinite(adapted).sum().item()}), flush=True)
    gc.collect()
assert np.isfinite(pretrained).all() and np.isfinite(adapted).all() and len(manifest['folds']) == 16
assert bindings == validate_replay_parent(PARENT, POOL, extension=TEACHER)
assert all(sha(p) == digest for p, digest in manifest['inputs'].items())
assert all(sha(p) == digest for p, digest in (PRODUCERS | EXPECTED | CACHE_EXPECTED).items())
assert verify_frozen_source(ENGINE) == receipt
for name, digest in assets['artifacts'].items():
    assert sha(model_root/name) == digest
for repo, root in roots.items():
    metadata = source_reg['source_repos'][repo]
    assert sha(VIEWS/f'{repo}-source.db') == metadata['source_db_sha256']
    for path, digest in metadata['source_files'].items():
        assert sha(root/path) == digest
# Only after fixed training/prediction ends, join the original strict references.
from ken.bench.retrieval import evaluate
cases = list(map(json.loads, (ROOT/'experiments/search-engine/datasets/development.jsonl').read_text().splitlines()))
for stage, predictions in (('pretrained', pretrained), ('adapted', adapted)):
    for fusion in ('raw', 'rrf'):
        responses = []
        for case in cases:
            qid, repo = case['id'], case['repo_id']
            rows, pool = case_rows[qid], pools[qid]
            base_order = sorted(range(len(pool)), key=lambda i: (-base_scores[rows[i]], i))
            pair_ranks, base_ranks = np.empty(len(pool)), np.empty(len(pool))
            base_ranks[base_order] = np.arange(1, len(pool)+1)
            pair_order = sorted(range(len(pool)), key=lambda i: (-predictions[rows[i]], base_ranks[i], i))
            pair_ranks[pair_order] = np.arange(1, len(pool)+1)
            values = predictions[rows] if fusion == 'raw' else 1/(60+pair_ranks)+1/(60+base_ranks)
            order = sorted(range(len(pool)), key=lambda i: (-pool[i].signals.get('exact', 0),
                -values[i], base_ranks[i], i))
            matches = [CodeMatch(pool[i].entity, float(values[i]), pool[i].passages,
                pool[i].passages[0].source_hash, pool[i].signals, pool[i].owned_regions) for i in order]
            request = SearchRequest(**requests[qid]['request'])
            matches = complete_evidence(matches, roots[repo], request)
            responses.append({'id': qid, **present(matches, roots[repo], request,
                profile_version=hashlib.sha256((receipt+stage+fusion+repo).encode()).hexdigest()).to_dict()})
        assert len(responses) == len({r['id'] for r in responses}) == 400
        report = evaluate(cases, responses, roots=roots)
        name = f'{stage}-{fusion}'
        (OUT/f'{name}-report.json').write_text(json.dumps(report, indent=2))
        (OUT/f'{name}-responses.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in responses))
        manifest['results'][name] = {'strict': report['strict_top1'], 'identity': report['identity_top1'],
                                    'missing': report['missing_response_ids']}
        (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'mode': name, **manifest['results'][name]}), flush=True)
for db in dbs.values():
    db.close()
