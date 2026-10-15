"""Original Semble official scoring in its installed environment, ALL1251 nofilter."""
import hashlib
import inspect
import json
import sys
from pathlib import Path
ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = ROOT/'output/frozen/semble-source7-views-v76'
OUT = ROOT/'output/development/semble-source7-views-v76b'
BASE = ROOT/'output/development/semble-public-1251-v1'
TOOL = Path('/private/tmp/ken-search-eval-20261014/tools/semble')
sys.path[:0] = [str(TOOL), str(ENGINE/'experiments/search-engine'), str(ENGINE/'src')]
from benchmarks.data import load_repo_specs, load_tasks
from benchmarks.metrics import ndcg_at_k
from semble_public_score import evaluate_rows
from ken.bench.source_receipts import verify_frozen_source

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

manifest = json.loads((OUT/'registration.json').read_text())
original = json.loads((BASE/'registration.json').read_text())
assert not (OUT/'report.json').exists()
assert verify_frozen_source(ENGINE) == manifest['engine_receipt']
assert Path(inspect.getfile(ndcg_at_k)).resolve() == TOOL/'benchmarks/metrics.py'
assert len(manifest['repos']) == 63
assert all(sha(path) == digest for path, digest in original['sources'].items())
file = OUT/'responses.jsonl'
response_hash = sha(file)
rows = list(map(json.loads, file.read_text().splitlines()))
assert len(rows) == len({r['id'] for r in rows}) == 1251
report = evaluate_rows(load_tasks(load_repo_specs()), {r['id']: r for r in rows})
assert report['queries'] == 1251 and report['repos'] == 63
assert sha(file) == response_hash
(OUT/'score-registration.json').write_text(json.dumps({'scope': 'ALL1251 official originalscore, errors/missing retained as0; no accuracyfilter',
    'script_sha256': sha(__file__), 'response_sha256': response_hash,
    'scorer_sha256': sha(TOOL/'benchmarks/metrics.py'),
    'adapter_sha256': sha(ENGINE/'experiments/search-engine/semble_public_score.py'),
    'source_bindings': original['sources'], 'python': sys.version}, indent=2))
(OUT/'report.json').write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if not k.startswith('by_') and k != 'per_query'}), flush=True)
