"""One instrumented actual API request; source snapshots copied, no engine edits."""
import cProfile
import hashlib
import json
import pstats
import sqlite3
import sys
from pathlib import Path

ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = ROOT/'output/frozen/cpu-bare-owned-code-v78'
sys.path[:0] = [str(ENGINE/'experiments/search-engine'), str(ENGINE/'src')]
import contextual_run as worker
from ken.bench.source_receipts import verify_frozen_source

OUT = ROOT/'output/analysis/cpu-hotpath-profile-v79'
BASE = ROOT/'output/analysis/c-source-reindex-v66c'
VIEWS = ROOT/'output/analysis/context-views-source7-v69'
OUT.mkdir(exist_ok=False)
requests = list(map(json.loads, (BASE/'requests/logrus.jsonl').read_text().splitlines()))
selected = next(row for row in requests if row['id'] == 'development-logrus-13')
(OUT/'request.jsonl').write_text(json.dumps(selected)+'\n')
original = sqlite3.connect(f'file:{BASE/"indices/logrus.db"}?mode=ro', uri=True)
copy = sqlite3.connect(OUT/'index.db')
original.backup(copy)
copy.close()
original.close()
roots = json.loads((ROOT/'experiments/search-engine/datasets/roots-development.json').read_text())
arguments = {'requests': OUT/'request.jsonl', 'index': OUT/'index.db', 'root': roots['logrus'],
    'numeric-model': ROOT/'output/analysis/source7-context-views-ranking-v69/contract_body251/logrus-numeric.json',
    'static-registration': ROOT/'output/models/static-comparison-registration.json',
    'translation-registration': ROOT/'output/models/es-en-cpu-registration-v21.json',
    'context-registration': ROOT/'output/models/cpu-context-registration-v42.json',
    'context-index': BASE/'context/logrus.db', 'context-source-registration': BASE/'context-registration.json',
    'source-view-index': VIEWS/'logrus-source.db', 'source-view-vectors': VIEWS/'logrus-vectors.npy',
    'source-view-registration': VIEWS/'registration.json', 'source-view-model-registration': VIEWS/'model-registration.json',
    'output': OUT/'worker'}
sys.argv = [str(ENGINE/'experiments/search-engine/contextual_run.py'), '--evidence-version', '3']
for key, value in arguments.items():
    sys.argv.extend(['--'+key, str(value)])
profile = cProfile.Profile()
original_search = worker.search
calls = 0


def instrumented(*args, **kwargs):
    global calls
    calls += 1
    return profile.runcall(original_search, *args, **kwargs) if calls == 2 else original_search(*args, **kwargs)


worker.search = instrumented
worker.main(expected_count=1)
assert calls == 2
profile.dump_stats(str(OUT/'actual-search.pstats'))
with (OUT/'profile-summary.txt').open('w') as stream:
    pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(45)
actual = json.loads((OUT/'worker/responses.jsonl').read_text())
expected = next(row for row in map(json.loads, (ROOT/'output/development/cpu-complete-owned-api-v74b-loo/responses.jsonl').read_text().splitlines()) if row['id'] == selected['id'])
assert actual == expected
record = {'scope': 'one instrumented actual API request;exact full response vs74b;not isolatedfinal latency/RSS',
    'id': selected['id'], 'engine_receipt': verify_frozen_source(ENGINE),
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'full_response_exact': True,
    'profiled_search_calls': 1, 'separate_unprofiled_warmup_calls': 1}
(OUT/'profile-registration.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record), flush=True)
