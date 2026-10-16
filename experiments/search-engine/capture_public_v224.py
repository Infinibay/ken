"""Capture frozen normal Ken API; worker inputs contain no expected answers."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import resource
import subprocess
import sys
import time

from public_benchmarks_v222 import sha

w = Path.cwd()
out = w / 'output/development/repoqa-core-v222'
parser = argparse.ArgumentParser()
parser.add_argument('track', choices=['repoqa', 'core'])
parser.add_argument('--group')
args = parser.parse_args()
registration = json.loads((out / 'registration.json').read_text())
engine = Path(registration['engine'])
assert sha(engine / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256']
for name, digest in json.loads((engine / 'SOURCE-MANIFEST.json').read_text())['files'].items():
    assert sha(engine / name) == digest
requests_path = out / f'{args.track}-requests.jsonl'
track_registration = json.loads((out / 'core-registration.json').read_text()) if args.track == 'core' else registration['repoqa']
assert sha(requests_path) == track_registration['requests_sha256']
requests = [json.loads(line) for line in requests_path.read_text().splitlines()]
assert len({r['id'] for r in requests}) == len(requests) == track_registration['queries']
source_path = out / f'{args.track}-sources.json'
assert sha(source_path) == track_registration['sources_sha256']
sources = json.loads(source_path.read_text())
environment = os.environ | {'PYTHONPATH': str(engine / 'src'), 'PYTHONDONTWRITEBYTECODE': '1',
    'HF_HUB_OFFLINE': '1', 'HF_HUB_CACHE': str(w / 'output/models/portable-public-hub-v143'),
    'KEN_CACHE_DIR': str(w / 'output/models/portable-public-prepared-v143'), 'KEN_INDEX_WORKERS': '0',
    'OPENBLAS_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
destination = out / f'{args.track}-capture-v224'
worker_pin = sha(Path(__file__))
def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)

if args.group is None:
    destination.mkdir(exist_ok=False)
    write(destination / 'registration.json', {'worker_sha256': worker_pin,
        'adapter_sha256': sha(Path(__file__).with_name('public_benchmarks_v222.py')),
        'requests_sha256': sha(requests_path), 'engine_manifest_sha256': registration['engine_manifest_sha256'],
        'labels_in_workers': False, 'reserve': 'CLOSED'})
    pins = {}
    for group_id in sorted({r['repo_id'] for r in requests}):
        started = time.perf_counter()
        with (destination / (group_id + '.log')).open('w') as log:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), args.track, '--group', group_id],
                env=environment, stdout=log, stderr=subprocess.STDOUT)
        folder = destination / group_id
        if result.returncode:
            folder.mkdir(exist_ok=True)
            failed = [{'id': r['id'], 'results': [], 'error': f'worker exit {result.returncode}; original log retained'}
                      for r in requests if r['repo_id'] == group_id]
            write(folder / 'responses.json', failed)
            write(folder / 'failure.json', {'exit': result.returncode, 'worker_sha256': worker_pin})
        for path in folder.iterdir():
            if path.is_file():
                pins[path.relative_to(destination).as_posix()] = sha(path)
        progress = {'closed': group_id, 'exit': result.returncode, 'elapsed_s': time.perf_counter() - started,
                    'closed_groups': len([p for p in pins if p.endswith('/responses.json')]),
                    'total_groups': len(sources), 'track': args.track}
        write(destination / 'progress.json', progress)
        print(json.dumps(progress), flush=True)
    write(destination / 'closure.json', {'status': 'All outputs closed before grading', 'queries': len(requests),
        'response_pins': pins, 'worker_sha256': worker_pin, 'requests_sha256': sha(requests_path)})
    sys.exit(0)

import ken
assert Path(ken.__file__).resolve().parents[2] == engine
from ken.retrieval.public import find_best, render
from ken.retrieval.connections import project_connection
from ken.retrieval.best_resources import default_resources

group = [r for r in requests if r['repo_id'] == args.group]
assert group and len({r['root'] for r in group}) == 1
root = Path(group[0]['root'])
source_pins = sources[args.group]['source_pins']
for name, digest in source_pins.items():
    assert sha(root / name) == digest
folder = destination / args.group
folder.mkdir(exist_ok=False)
if (root / '.ken').exists():
    previous = out / 'repoqa-capture' / args.group / 'ownership.json'
    assert args.track == 'repoqa' and previous.is_file(), 'Unexpected preexisting state'
    prior_owner = json.loads(previous.read_text())
    assert prior_owner['root'] == str(root) and prior_owner['state_preexisting'] is False
    assert prior_owner['source_pins_sha256'] == sha(source_path)

write(folder / 'ownership.json', {'root': str(root), 'state_preexisting': False,
    'source_pins_sha256': sha(source_path), 'only_creates': '.ken'})
if args.track == 'core':
    # Source-only exact-text cache is shared between public eligible snapshots.
    # Each normal engine still creates/validates its own source-bound snapshot.
    shared_cache = out / 'core-context-cache'
    shared_cache.mkdir(exist_ok=True)
    (root / '.ken').mkdir()
    (root / '.ken/search-context').symlink_to(shared_cache, target_is_directory=True)
started = time.perf_counter()
with (folder / 'prepare.log').open('w') as log:
    subprocess.run([sys.executable, '-m', 'ken', 'retrieval', 'prepare', '--path', str(root), '--json'],
        env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
preparation_ms = (time.perf_counter() - started) * 1000
responses = []
with project_connection(root) as conn:
    indexed_paths = [r[0] for r in conn.execute('SELECT path FROM ci_files ORDER BY path')]
    assert not any(p.startswith('.ken/') for p in indexed_paths)
    assert set(indexed_paths) <= source_pins.keys()
    write(folder / 'index-coverage.json', {'indexed_files': len(indexed_paths), 'source_files': len(source_pins),
        'not_indexed': sorted(source_pins.keys() - set(indexed_paths)),
        'owners': conn.execute('SELECT COUNT(DISTINCT entity_key) FROM ci_passages').fetchone()[0]
                  if 'entity_key' in [r[1] for r in conn.execute('PRAGMA table_info(ci_passages)')] else None})
    warmup_started = time.perf_counter()
    warmup = find_best(conn, root, 'find code that prepares a value', scope=group[0]['scope'],
                       piece_kind=group[0]['piece_kind'])
    assert warmup.get('ok') is not False, warmup
    warmup_ms = (time.perf_counter() - warmup_started) * 1000
    for request in group:
        before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        try:
            value = find_best(conn, root, request['query'], scope=request['scope'],
                piece_kind=request['piece_kind'], limit=10, max_chars=12000)
            if value.get('ok') is False:
                raise ValueError(str(value))
            assert len(value['results']) <= 10
            assert not any(r.get('stale') for r in value['results'])
            compact = render(value)
            json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        except Exception as error:
            value = {'results': [], 'error': f'{type(error).__name__}: {error}'}
            compact = value['error']
        after = resource.getrusage(resource.RUSAGE_SELF)
        responses.append({'id': request['id'], **value, 'compact': compact,
            'elapsed_ms': (time.perf_counter() - started) * 1000,
            'cpu_ms': ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000})
        write(folder / 'progress.json', {'captured': len(responses), 'queries': len(group)})
for name, digest in source_pins.items():
    assert sha(root / name) == digest
resources = default_resources()
assert list(resources.neural.providers) == list(resources.context.providers) == ['CPUExecutionProvider']
assert resources.neural._max_tokens == 1024
heavy = [name for name in ['torch', 'transformers', 'sentence_transformers'] if name in sys.modules]
assert not heavy
write(folder / 'responses.json', responses)
write(folder / 'provenance.json', {'complete': True, 'preparation_ms': preparation_ms, 'warmup_ms': warmup_ms,
    'providers': list(resources.neural.providers), 'reranker_tokens': 1024, 'heavy_imports': heavy,
    'query_process_peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'prepare_child_peak_rss_native': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
    'worker_sha256': worker_pin, 'engine_manifest_sha256': registration['engine_manifest_sha256'],
    'runtime': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}})
