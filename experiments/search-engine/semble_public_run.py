"""Public queries only: pinned-corpus export and isolated CPU retrieval workers."""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path


MODES = {'ken': ('ken-symbol-api', 'ken-file-api', 'ken-symbol-role', 'ken-file-role'),
         'semble': ('semble-native',)}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temp.replace(path)


def export(args):
    sys.path.insert(0, str(args.tool_root))
    from benchmarks.data import load_repo_specs, load_tasks
    specs = load_repo_specs()
    tasks = load_tasks(specs)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'requests').mkdir()
    rows = []
    for i, task in enumerate(tasks):
        spec = specs[task.repo]
        checkout = args.repo_root/task.repo
        root = checkout/spec.benchmark_root if spec.benchmark_root else checkout
        head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        if head != spec.revision:
            raise ValueError('wrong corpus revision')
        if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True):
            raise ValueError('dirty benchmark repository')
        rows.append({'id': f'semble-{i:04d}', 'repo_id': task.repo, 'repo_commit': head,
                     'query': task.query, 'root': str(root.resolve())})
    (args.output/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    for repo in specs:
        group = [r for r in rows if r['repo_id'] == repo]
        (args.output/'requests'/f'{repo}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in group))
    sources = [args.tool_root/'benchmarks'/name for name in ('data.py', 'metrics.py', 'run_benchmark.py', 'repos.json')]
    sources += sorted((args.tool_root/'benchmarks/annotations').glob('*.json'))
    write(args.output/'registration.json', {'queries': len(rows), 'repos': len(specs),
        'requests_sha256': sha(args.output/'requests.jsonl'),
        'tool_commit': subprocess.check_output(['git', '-C', str(args.tool_root), 'rev-parse', 'HEAD'], text=True).strip(),
        'sources': {str(p): sha(p) for p in sources}, 'runner_sha256': sha(__file__),
        'specs': [dataclasses.asdict(s) for s in specs.values()]})


def request_rows(path):
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    allowed = {'id', 'repo_id', 'repo_commit', 'query', 'root'}
    if any(set(r) != allowed for r in rows) or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('unique public-only requests required')
    if len({r['root'] for r in rows}) != 1:
        raise ValueError('one repository per isolated worker')
    for r in rows:
        if subprocess.check_output(['git', '-C', r['root'], 'rev-parse', 'HEAD'], text=True).strip() != r['repo_commit']:
            raise ValueError('source revision changed')
    return rows


def ken_worker(args, rows, metadata):
    import ken
    from ken.bench.ranking_controls import prefer_requested_role
    from ken.bench.runner import source_manifest
    from ken.bench.source_receipts import verify_frozen_source
    from ken.bench.static_embeddings import StaticEmbeddingControl
    from ken.db import connect, init_schema
    from ken.gitignore_filter import iter_files
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.indexing import index_project
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.presentation import present
    from ken.retrieval.profile import RetrievalProfile
    from ken.retrieval.ranking import rank_candidates
    from ken.retrieval.service import search
    actual = Path(ken.__file__).resolve().parents[2]
    if actual != args.engine_root.resolve():
        raise ValueError('wrong engine import')
    metadata['engine_receipt_sha256'] = verify_frozen_source(actual)
    registration = json.loads(args.registration.read_text())
    model = next(r for r in registration if r['model_id'] == 'minishlab/potion-code-16M-v2')
    encoder = StaticEmbeddingControl(Path(model['root']), model)
    profile = RetrievalProfile(encoder.spec, encoder.spec)
    encoders = {'identity': encoder, 'behavior': encoder}
    metadata.update(profile=profile.to_dict(), profile_sha256=profile.fingerprint,
                    encoder=encoder.identity, registration_sha256=sha(args.registration))
    root = Path(rows[0]['root'])
    conn = connect(args.output/'source.db')
    try:
        init_schema(conn)
        files = list(iter_files(root))
        metadata['source_manifest'] = source_manifest(root, files)
        write(args.output/'source-files.json', {p.as_posix(): sha(root/p) for p in files})
        started = time.perf_counter()
        metadata['index_stats'] = dataclasses.asdict(index_project(conn, root, files,
            profile=profile, encoders=encoders))
        metadata['index_seconds'] = time.perf_counter()-started
        metadata['indexed_files'] = conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]
        metadata['passages'] = conn.execute('SELECT COUNT(*) FROM ci_passages').fetchone()[0]
        write(args.output/'provenance.json', metadata)
        search(conn, root, SearchRequest('warm CPU source index before timed queries'), profile=profile, encoders=encoders)
        responses = []
        for row in rows:
            modes = {}
            for target in ('symbol', 'file'):
                started = time.perf_counter()
                try:
                    value = search(conn, root, SearchRequest(row['query'], target=target),
                                   profile=profile, encoders=encoders).to_dict()
                    json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    value = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
                value['elapsed_ms'] = (time.perf_counter()-started)*1000
                modes[f'ken-{target}-api'] = value
            started = time.perf_counter()
            try:
                request = SearchRequest(row['query'])
                candidates = retrieve(conn, root, request, profile, encoders=encoders)
                ordered = prefer_requested_role(request, rank_candidates(request, candidates))
                for target in ('symbol', 'file'):
                    modes[f'ken-{target}-role'] = present(ordered, root,
                        SearchRequest(row['query'], target=target), profile_version=profile.fingerprint).to_dict()
            except Exception as exc:
                for target in ('symbol', 'file'):
                    modes[f'ken-{target}-role'] = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
            metadata.setdefault('role_combined_ms', []).append((time.perf_counter()-started)*1000)
            responses.append({'id': row['id'], 'modes': modes})
        return responses
    finally:
        conn.close()


def semble_worker(args, rows, metadata):
    os.environ['SEMBLE_CACHE_LOCATION'] = str((args.output/'cache').resolve())
    os.environ['SEMBLE_INDEX_WORKERS'] = '4'
    from semble import SembleIndex
    from semble.utils import format_results
    from semble.version import __version__
    registration = json.loads(args.registration.read_text())
    model = next(r for r in registration if r['model_id'] == 'minishlab/potion-code-16M-v2')
    model_path = Path(model['root'])
    # The registered copy is also verified by the Ken encoder, before any result.
    for name, artifact in model['artifacts'].items():
        if sha(model_path/name) != artifact['sha256']:
            raise ValueError('Semble model bytes changed')
    metadata.update(version=__version__, model=model)
    started = time.perf_counter()
    index = SembleIndex.from_path(Path(rows[0]['root']), model_path=str(model_path))
    metadata['index_seconds'] = time.perf_counter()-started
    metadata['index_stats'] = dataclasses.asdict(index.stats)
    write(args.output/'provenance.json', metadata)
    responses = []
    for row in rows:
        latencies = []
        try:
            for _ in range(5):
                started = time.perf_counter()
                hits = index.search(row['query'], top_k=10, alpha=None, rerank=True)
                latencies.append((time.perf_counter()-started)*1000)
            value = {'full_results': [dataclasses.asdict(hit) for hit in hits],
                'native': format_results(row['query'], hits, 40),
                'elapsed_ms': statistics.median(latencies), 'five_runs_ms': latencies}
        except Exception as exc:
            value = {'full_results': [], 'error': f'{type(exc).__name__}: {exc}'}
        responses.append({'id': row['id'], 'modes': {'semble-native': value}})
    metadata['indexed_paths'] = sorted({chunk.file_path for chunk in index.chunks})
    return responses


def worker(args):
    rows = request_rows(args.requests)
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {'requests_sha256': sha(args.requests), 'runner_sha256': sha(__file__),
        'repo': rows[0]['repo_id'], 'revision': rows[0]['repo_commit'], 'root': rows[0]['root'],
        'device': 'cpu', 'platform': platform.platform(), 'python': sys.version,
        'planned_ids': [r['id'] for r in rows], 'engine': args.engine}
    write(args.output/'provenance.json', metadata)
    started = time.perf_counter()
    responses = (ken_worker if args.engine == 'ken' else semble_worker)(args, rows, metadata)
    metadata.update(complete=True, total_seconds=time.perf_counter()-started,
                    peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    heavy_modules_loaded=[name for name in ('torch', 'transformers', 'mlx') if name in sys.modules])
    write(args.output/'responses.json', responses)
    write(args.output/'provenance.json', metadata)
    print(json.dumps({k: metadata[k] for k in ('repo', 'engine', 'total_seconds', 'peak_rss_native')}), flush=True)


def run(args):
    rows = [json.loads(l) for l in (args.output/'requests.jsonl').read_text().splitlines()]
    (args.output/args.engine).mkdir(exist_ok=True)
    for repo in sorted({r['repo_id'] for r in rows}):
        output = args.output/args.engine/repo
        requests = args.output/'requests'/f'{repo}.jsonl'
        if output.exists():
            provenance = json.loads((output/'provenance.json').read_text())
            if (provenance.get('complete') and provenance['runner_sha256'] == sha(__file__)
                    and provenance['requests_sha256'] == sha(requests)):
                print(json.dumps({'reused': repo, 'engine': args.engine}), flush=True)
                continue
            raise ValueError(f'incomplete or different run requires a new output directory: {output}')
        command = [str(args.python), str(Path(__file__).resolve()), 'worker', '--engine', args.engine,
            '--requests', str(requests), '--output', str(output), '--engine-root', str(args.engine_root),
            '--registration', str(args.registration), '--tool-root', str(args.tool_root)]
        print(json.dumps({'starting': repo, 'engine': args.engine}), flush=True)
        with (args.output/args.engine/f'{repo}.log').open('w') as log:
            process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if process.returncode:
            # Retain the full denominator and all failing native evidence.
            group = [r for r in rows if r['repo_id'] == repo]
            output.mkdir(exist_ok=True)
            error = f'isolated index/search worker exit {process.returncode}; see {repo}.log'
            write(output/'responses.json', [{'id': r['id'], 'modes': {
                mode: {'results': [], 'error': error} for mode in MODES[args.engine]}} for r in group])
            metadata = json.loads((output/'provenance.json').read_text()) if (output/'provenance.json').exists() else {}
            metadata.update(complete=True, worker_error=error, runner_sha256=sha(__file__),
                            requests_sha256=sha(requests))
            write(output/'provenance.json', metadata)
        print(json.dumps({'finished': repo, 'engine': args.engine, 'exit': process.returncode}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('export', 'run', 'worker'))
    parser.add_argument('--engine', choices=('ken', 'semble'))
    parser.add_argument('--tool-root', type=Path, required=True)
    parser.add_argument('--engine-root', type=Path)
    parser.add_argument('--repo-root', type=Path)
    parser.add_argument('--registration', type=Path)
    parser.add_argument('--requests', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path)
    args = parser.parse_args()
    {'export': export, 'run': run, 'worker': worker}[args.action](args)


if __name__ == '__main__':
    main()
