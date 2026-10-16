"""Sequential native CORE capture. Inputs contain source and queries, never qrels."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import resource
import shutil
import subprocess
import sys
import time

from public_benchmarks_v222 import sha


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(path)


def check_sources(group):
    for name, digest in group['source_pins'].items():
        assert sha(Path(group['root']) / name) == digest, name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path.cwd() / 'output/development/core-native-v235')
    parser.add_argument('--group')
    parser.add_argument('--route', choices=['symbols', 'files'])
    args = parser.parse_args()
    out = args.out.resolve()
    registration = json.loads((out / 'registration.json').read_text())
    assert sha(out / 'native-requests.json') == registration['native_requests_sha256']
    groups = json.loads((out / 'native-requests.json').read_text())
    engine = Path(registration['engine'])
    assert sha(engine / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256']
    for name, digest in json.loads((engine / 'SOURCE-MANIFEST.json').read_text())['files'].items():
        assert sha(engine / name) == digest, name
    producer = Path(__file__).resolve()
    pins = {p.name: sha(p) for p in producer.parent.glob('*.py')}
    environment = os.environ | {
        'PYTHONPATH': str(engine / 'src'), 'PYTHONDONTWRITEBYTECODE': '1',
        'HF_HUB_OFFLINE': '1',
        'HF_HUB_CACHE': str(Path.cwd() / 'output/models/portable-public-hub-v143'),
        'KEN_CACHE_DIR': str(Path.cwd() / 'output/models/portable-public-prepared-v143'),
        'KEN_INDEX_WORKERS': '0', 'OPENBLAS_NUM_THREADS': '1',
        'VECLIB_MAXIMUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
    }
    destination = out / 'capture'
    if args.group is None:
        destination.mkdir(exist_ok=False)
        write(destination / 'registration.json', {
            'producer_pins': pins, 'inputs_sha256': sha(out / 'registration.json'),
            'requests_sha256': sha(out / 'native-requests.json'),
            'labels_in_workers': False, 'reserve': 'CLOSED'})
        closed = {}
        for number, group in enumerate(groups, 1):
            started = time.perf_counter()
            with (destination / (group['instance_id'] + '.log')).open('w') as log:
                result = subprocess.run([sys.executable, str(producer), '--out', str(out),
                    '--group', group['instance_id']], env=environment, stdout=log, stderr=subprocess.STDOUT)
            folder = destination / group['instance_id']
            if result.returncode:
                folder.mkdir(exist_ok=True)
                write(folder / 'failure.json', {'exit': result.returncode, 'log_retained': True})
                for route in registration['routes']:
                    path = folder / (route + '.json')
                    if not path.exists():
                        write(path, {'id': group['instance_id'], 'results': [],
                            'error': f'group process exit {result.returncode}', 'elapsed_ms': None})
            closed.update({p.relative_to(destination).as_posix(): sha(p)
                           for p in folder.iterdir() if p.is_file()})
            progress = {'closed': number, 'total': len(groups), 'instance_id': group['instance_id'],
                        'exit': result.returncode, 'elapsed_s': time.perf_counter() - started}
            write(destination / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
        for name, digest in pins.items():
            assert sha(producer.parent / name) == digest, 'producer changed during run'
        write(destination / 'closure.json', {'all_outputs_closed': True, 'groups': len(groups),
            'unique_queries_per_route': len(groups), 'level_cases_per_route': registration['level_cases'],
            'response_pins': closed, 'producer_pins': pins,
            'requests_sha256': sha(out / 'native-requests.json'), 'reserve': 'CLOSED'})
        return

    capture_registration = json.loads((destination / 'registration.json').read_text())
    for name, digest in capture_registration['producer_pins'].items():
        assert sha(producer.parent / name) == digest
    group = next(g for g in groups if g['instance_id'] == args.group)
    root = Path(group['root'])
    check_sources(group)
    folder = destination / args.group
    if args.route is None:
        folder.mkdir(exist_ok=False)
        assert not (root / '.ken').exists(), 'Unexpected existing index'
        write(folder / 'ownership.json', {'root': str(root), 'index_preexisting': False,
            'source_pins': group['source_pins'], 'native_requests_sha256': sha(out / 'native-requests.json')})
        shared_cache = out / 'source-context-cache'
        shared_cache.mkdir(exist_ok=True)
        (root / '.ken').mkdir()
        (root / '.ken/search-context').symlink_to(shared_cache, target_is_directory=True)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.perf_counter()
        with (folder / 'prepare.log').open('w') as log:
            result = subprocess.run([sys.executable, '-m', 'ken', 'retrieval', 'prepare',
                '--path', str(root), '--json'], env=environment, stdout=log, stderr=subprocess.STDOUT)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        write(folder / 'preparation.json', {'exit': result.returncode,
            'elapsed_ms': (time.perf_counter() - started) * 1000,
            'cpu_ms': ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000,
            'peak_rss_native': after.ru_maxrss, 'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
            'index_bytes_before_query': sum(p.stat().st_size for p in (root / '.ken').rglob('*')
                                            if p.is_file() and not p.is_symlink())})
        if result.returncode:
            raise RuntimeError(f'preparation failed: {result.returncode}')
        for route in registration['routes']:
            with (folder / (route + '.log')).open('w') as log:
                query_result = subprocess.run([sys.executable, str(producer), '--out', str(out),
                    '--group', args.group, '--route', route], env=environment,
                    stdout=log, stderr=subprocess.STDOUT)
            if query_result.returncode:
                write(folder / (route + '.json'), {'id': args.group, 'results': [],
                    'error': f'query process exit {query_result.returncode}', 'elapsed_ms': None})
        check_sources(group)
        write(folder / 'index-cleanup.json', {'root': str(root),
            'index_bytes_after_queries': sum(p.stat().st_size for p in (root / '.ken').rglob('*')
                                            if p.is_file() and not p.is_symlink()),
            'source_verified_after_capture': True, 'remove_only_owned_index': True})
        shutil.rmtree(root / '.ken')
        return

    import ken
    assert Path(ken.__file__).resolve().parents[2] == engine
    from ken.retrieval.public import find_best, render
    from ken.retrieval.connections import project_connection
    from ken.retrieval.best_resources import default_resources
    route = registration['routes'][args.route]
    with project_connection(root) as conn:
        if args.route == 'symbols':
            paths = [row[0] for row in conn.execute('SELECT path FROM ci_files ORDER BY path')]
            assert set(paths) <= group['source_pins'].keys()
            roles = dict(conn.execute('SELECT role,COUNT(*) FROM ci_passages GROUP BY role'))
            write(folder / 'index-coverage.json', {'source_files': len(group['source_pins']),
                'indexed_files': len(paths), 'not_indexed': sorted(group['source_pins'].keys() - set(paths)),
                'passages_by_role': roles, 'symbols': conn.execute('SELECT COUNT(*) FROM ci_symbols').fetchone()[0]})
        started = time.perf_counter()
        warmup = find_best(conn, root, 'find code that prepares a value', **route)
        assert warmup.get('ok') is not False, warmup
        warmup_ms = (time.perf_counter() - started) * 1000
        before = resource.getrusage(resource.RUSAGE_SELF)
        started = time.perf_counter()
        try:
            value = find_best(conn, root, group['query'], **route, limit=10, max_chars=12000)
            if value.get('ok') is False:
                raise ValueError(str(value))
            assert len(value['results']) <= 10
            assert not any(r.get('stale') for r in value['results'])
            compact = render(value)
            json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        except Exception as error:
            value = {'results': [], 'error': f'{type(error).__name__}: {error}'}
            compact = value['error']
        elapsed_ms = (time.perf_counter() - started) * 1000
        after = resource.getrusage(resource.RUSAGE_SELF)
    resources = default_resources()
    assert list(resources.neural.providers) == list(resources.context.providers) == ['CPUExecutionProvider']
    assert resources.neural._max_tokens == 1024
    heavy = [n for n in ['torch', 'transformers', 'sentence_transformers'] if n in sys.modules]
    assert not heavy
    check_sources(group)
    write(folder / (args.route + '.json'), {'id': group['instance_id'], **value, 'compact': compact,
        'elapsed_ms': elapsed_ms,
        'cpu_ms': ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000})
    write(folder / (args.route + '-provenance.json'), {'complete': True, 'route': route,
        'query_sha256': group['query_sha256'], 'warmup_ms': warmup_ms,
        'providers': list(resources.neural.providers), 'reranker_tokens': 1024, 'heavy_imports': heavy,
        'query_process_peak_rss_native': after.ru_maxrss,
        'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
        'engine_manifest_sha256': registration['engine_manifest_sha256'],
        'runtime': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}})


if __name__ == '__main__':
    main()
