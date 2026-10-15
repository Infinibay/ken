"""ALL1251 actual CPU API requests only after complete source7/63 views and devfit."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import ken
from ken.bench.source_receipts import verify_frozen_source

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
FROZEN = Path(ken.__file__).resolve().parents[2]
BASE = ROOT/'output/development/semble-public-1251-v1'
SOURCE = ROOT/'output/analysis/semble-source7-views-source-v76'
FIT = ROOT/'output/analysis/semble-source7-views-fit-v76'
OUT = ROOT/'output/development/semble-source7-views-v76b'
MODEL = FIT/'all-development-numeric.json'
WORKER = FROZEN/'experiments/search-engine/contextual_public_run.py'
OUT.mkdir(exist_ok=False)
for name in ('requests', 'indices', 'workers'):
    (OUT/name).mkdir()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


receipt = verify_frozen_source(FROZEN)
manifest = {'scope': 'ALL1251originalpublicqueries/63pins actualfileAPI/source7+views251/evidence3;one model trainedonly16disjointdevrepos;notblindacceptance/resourcescertificate',
    'script_sha256': sha(__file__), 'worker_sha256': sha(WORKER), 'engine_receipt': receipt,
    'score_controller_sha256': sha('/private/tmp/ken-semble-source7-views-score-v76b.py'),
    'protocol_sha256': sha(FROZEN/'experiments/search-engine/semble-public-source7-views-v76.md'),
    'binding_supplement_sha256': sha(ROOT/'experiments/search-engine/semble-public-source7-views-v76b.md'),
    'repos': {}, 'source_tree': json.loads((FROZEN/'SOURCE-MANIFEST.json').read_text())['tree_sha256']}
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
while True:
    try:
        source_reg = json.loads((SOURCE/'registration.json').read_text())
        views_reg = json.loads((SOURCE/'views/registration.json').read_text())
        fit_reg = json.loads((FIT/'registration.json').read_text())
        if source_reg.get('complete') is True and len(views_reg['source_repos']) == 63:
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
assert source_reg['engine_receipt'] == fit_reg['engine_receipt'] == receipt
assert len(source_reg['source_repos']) == len(source_reg['context_repos']) == 63
assert set(views_reg['repositories']) == set(views_reg['source_repos']) == set(source_reg['repositories'])
assert sha(MODEL) == fit_reg['numeric_model_sha256']
assert sha(BASE/'registration.json') == source_reg['inputs'][str(BASE/'registration.json')]
original = json.loads((BASE/'registration.json').read_text())
assert all(sha(path) == digest for path, digest in original['sources'].items())
# Independent review of the source/fit boundary precedes the public query loop.
print(json.dumps({'awaiting_public_prequery_review': True}), flush=True)
while not (OUT/'PUBLIC-PRE-QUERY-REVIEW-ACCEPTED.json').is_file():
    time.sleep(2)
assert all(sha(path) == digest for path, digest in original['sources'].items())
query_path = BASE/'requests.jsonl'
old_public = json.loads((ROOT/'output/development/semble-contextual-v48/registration.json').read_text())
assert sha(query_path) == original['requests_sha256'] == old_public['public_requests_sha256']
# First public query read in this pipeline, after ALL63 source artifacts and fixed fit.
rows = list(map(json.loads, (BASE/'requests.jsonl').read_text().splitlines()))
assert len(rows) == len({r['id'] for r in rows}) == 1251
repos = sorted({r['repo_id'] for r in rows})
assert len(repos) == 63 and set(repos) == set(views_reg['repositories'])
assert set(repos).isdisjoint(fit_reg['training_repos'])
manifest['inputs'] = {str(p): sha(p) for p in (MODEL, FIT/'registration.json', SOURCE/'registration.json',
    SOURCE/'context-registration.json', SOURCE/'views/registration.json', BASE/'registration.json', BASE/'requests.jsonl',
    ROOT/'experiments/search-engine/semble-public-source7-views-v76b.md')}
manifest['training_repos'] = fit_reg['training_repos']
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
environment = dict(os.environ, PYTHONPATH=str(FROZEN/'src'), OMP_NUM_THREADS='1',
    OPENBLAS_NUM_THREADS='1', TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1')
responses = []
for repo in repos:
    public = [r for r in rows if r['repo_id'] == repo]
    root = Path(public[0]['root'])
    assert len({r['root'] for r in public}) == len({r['repo_commit'] for r in public}) == 1
    assert subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() == public[0]['repo_commit']
    assert not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)
    source_index = SOURCE/'indices'/f'{repo}.db'
    assert sha(source_index) == source_reg['source_repos'][repo]['new_source_index_sha256']
    index = OUT/'indices'/f'{repo}.db'
    source = sqlite3.connect(f'file:{source_index}?mode=ro', uri=True)
    target = sqlite3.connect(index)
    source.backup(target)
    target.close()
    source.close()
    request_file = OUT/'requests'/f'{repo}.jsonl'
    requests = [{'id': r['id'], 'repo_id': repo, 'request': {'query': r['query'],
        'target': 'file', 'purpose': 'auto', 'limit': 10, 'max_chars': 12000}} for r in public]
    request_file.write_text(''.join(json.dumps(r)+'\n' for r in requests))
    started = time.perf_counter()
    arguments = [sys.executable, str(WORKER), '--evidence-version', '3',
        '--requests', str(request_file), '--index', str(index), '--root', str(root),
        '--numeric-model', str(MODEL), '--static-registration', str(ROOT/'output/models/static-comparison-registration.json'),
        '--translation-registration', str(ROOT/'output/models/es-en-cpu-registration-v21.json'),
        '--context-registration', str(ROOT/'output/models/cpu-context-registration-v42.json'),
        '--context-index', str(SOURCE/'context'/f'{repo}.db'),
        '--context-source-registration', str(SOURCE/'context-registration.json'),
        '--source-view-index', str(SOURCE/'views'/f'{repo}-source.db'),
        '--source-view-vectors', str(SOURCE/'views'/f'{repo}-vectors.npy'),
        '--source-view-registration', str(SOURCE/'views/registration.json'),
        '--source-view-model-registration', str(SOURCE/'views/model-registration.json'),
        '--output', str(OUT/'workers'/repo)]
    with (OUT/'workers'/f'{repo}-stdout.log').open('w') as stdout, (OUT/'workers'/f'{repo}-stderr.log').open('w') as stderr:
        result = subprocess.run(arguments, env=environment, stdout=stdout, stderr=stderr)
    output = OUT/'workers'/repo/'responses.jsonl'
    produced = list(map(json.loads, output.read_text().splitlines())) if output.exists() else []
    expected = {r['id'] for r in requests}
    for request in requests:
        matching = [p for p in produced if p.get('id') == request['id']]
        responses.append(matching[0] if result.returncode == 0 and len(matching) == 1 else
            {'id': request['id'], 'results': [], 'error': f'worker exit={result.returncode},response_count={len(matching)}'})
    manifest['repos'][repo] = {'queries': len(requests), 'worker_exit_code': result.returncode,
        'request_sha256': sha(request_file), 'response_sha256': sha(output) if output.exists() else None,
        'unexpected_ids': sorted({r.get('id', '') for r in produced}-expected), 'ms': (time.perf_counter()-started)*1000}
    assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
    assert verify_frozen_source(FROZEN) == receipt
    (OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
    (OUT/'responses.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in responses))
    print(json.dumps({'repo': repo, 'queries_completed': len(responses), 'worker_exit_code': result.returncode}), flush=True)
assert len(responses) == len({r['id'] for r in responses}) == 1251
assert all(sha(path) == digest for path, digest in original['sources'].items())
# Semble's installed environment owns official scoring, independently of API imports.
scorer = Path('/private/tmp/ken-semble-source7-views-score-v76b.py')
assert manifest['score_controller_sha256'] == sha(scorer)
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
result = subprocess.run(['/private/tmp/ken-search-eval-20261014/venv/bin/python', str(scorer)],
                        env=dict(environment, PYTHONPATH=str(FROZEN/'src')))
assert result.returncode == 0
