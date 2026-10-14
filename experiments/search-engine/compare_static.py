"""Matched static controls: source-only preparation and public-only CPU requests."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sqlite3
import sys
import time
from pathlib import Path

import ken
import numpy as np

from ken.bench.ranking_controls import prefer_requested_role
from ken.bench.runner import source_manifest
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect
from ken.gitignore_filter import iter_files
from ken.retrieval.candidates import retrieve
from ken.retrieval.model import SearchRequest
from ken.retrieval.presentation import present
from ken.retrieval.profile import RetrievalProfile
from ken.retrieval.ranking import rank_candidates
from ken.retrieval.representations import index_embeddings
from ken.retrieval.service import search
from ken.retrieval.storage import load_passage_map


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'measure'])
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--requests', type=Path)
    args = parser.parse_args()
    source_root = Path(ken.__file__).resolve().parents[2]
    if source_root != Path(__file__).resolve().parents[2]:
        raise ValueError('driver and engine must use the same frozen source')
    receipt = verify_frozen_source(source_root)
    registrations = json.loads(args.registration.read_text())
    registered = [r for r in registrations if r['model_id'] == args.model_id]
    if len(registered) != 1:
        raise ValueError('exactly one pinned model registration required')
    encoder = StaticEmbeddingControl(Path(registered[0]['root']), registered[0])
    profile = RetrievalProfile(encoder.spec, encoder.spec)
    encoders = {'identity': encoder, 'behavior': encoder}
    if args.phase == 'prepare':
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output/'indices').mkdir()
        metadata = {'source_receipt_sha256': receipt, 'profile_sha256': profile.fingerprint,
            'source_indices': str(args.source), 'source_passages_changed': False,
            'encoder': encoder.identity, 'registration_sha256': sha(args.registration), 'repos': {}}
        source_provenance = json.loads((args.source/'provenance.json').read_text())
        write(args.output/'profile.json', profile.to_dict())
        for path in sorted((args.source/'indices').glob('*.db')):
            start = time.perf_counter()
            original = connect(path)
            dest = connect(args.output/'indices'/path.name)
            try:
                # Consistent SQLite backup, including committed WAL contents.
                original.backup(dest)
                before = load_passage_map(original)
                if load_passage_map(dest) != before:
                    raise ValueError('source passages differ before encoding')
                index_embeddings(dest, profile, encoders=encoders)
                if load_passage_map(dest) != before:
                    raise ValueError('encoding changed source passages')
                repo = path.stem
                stats = source_provenance['repos'][repo]['index_stats'][repo]
                metadata['repos'][repo] = {'source_index': sha(path),
                    'passages': len(before), 'files': stats['files'],
                    'source_tree_sha256': stats['source_tree_sha256'],
                    'seconds': time.perf_counter()-start}
            finally:
                original.close(); dest.close()
            write(args.output/'source-preparation.json', metadata)
            print(json.dumps({'prepared': repo, **metadata['repos'][repo]}), flush=True)
        metadata['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metadata['complete'] = True
        write(args.output/'source-preparation.json', metadata)
        return
    if args.requests is None:
        raise ValueError('public-only request file required')
    requests = [json.loads(line) for line in args.requests.read_text().splitlines()]
    allowed = {'id', 'repo_id', 'repo_commit', 'query', 'root'}
    if any(set(r) != allowed for r in requests) or len({r['id'] for r in requests}) != len(requests):
        raise ValueError('unique public-only requests required; no reference metadata')
    prepared = json.loads((args.output/'source-preparation.json').read_text())
    if not prepared.get('complete') or prepared['profile_sha256'] != profile.fingerprint:
        raise ValueError('complete matching prepared index required')
    if prepared['source_receipt_sha256'] != receipt:
        raise ValueError('prepared source receipt differs')
    measure = args.output/'measurement'
    measure.mkdir(exist_ok=False)
    metadata = {'source_receipt_sha256': receipt, 'profile_sha256': profile.fingerprint,
        'requests_sha256': sha(args.requests), 'registration_sha256': sha(args.registration),
        'encoder': encoder.identity, 'case_ids': [r['id'] for r in requests],
        'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version,
        'scope': 'prepared public API + JSON; role is a separate bench control; no CLI/MCP transport',
        'timings': [], 'repos': {}}
    for repo in sorted({r['repo_id'] for r in requests}):
        selected = [r for r in requests if r['repo_id'] == repo]
        if len({r['root'] for r in selected}) != 1:
            raise ValueError('one source root per repository required')
        root = Path(selected[0]['root'])
        stats = source_manifest(root, iter_files(root))
        if any(stats[k] != prepared['repos'][repo][k] for k in ('files', 'source_tree_sha256')):
            raise ValueError('source corpus changed since preparation')
        metadata['repos'][repo] = stats
        conn = connect(args.output/'indices'/f'{repo}.db')
        try:
            search(conn, root, SearchRequest('warm CPU source index before timed queries'),
                profile=profile, encoders=encoders)
            for row in selected:
                request = SearchRequest(row['query'])
                started = time.perf_counter()
                try:
                    raw = search(conn, root, request, profile=profile, encoders=encoders).to_dict()
                    json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    raw = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
                api_ms = (time.perf_counter()-started)*1000
                started = time.perf_counter()
                candidates = []
                try:
                    candidates = retrieve(conn, root, request, profile, encoders=encoders)
                    matches = prefer_requested_role(request, rank_candidates(request, candidates))
                    role = present(matches, root, request, profile_version=profile.fingerprint).to_dict()
                    json.dumps(role, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    role = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
                role_ms = (time.perf_counter()-started)*1000
                for name, result in (('responses.jsonl', raw), ('role-responses.jsonl', role)):
                    with (measure/name).open('a') as stream:
                        stream.write(json.dumps({'id': row['id'], **result}, ensure_ascii=False)+'\n')
                diagnostic = {'id': row['id'], 'candidates': [
                    {'path': c.entity.path, 'entity': c.entity.to_dict(), 'signals': c.signals,
                     'passages': [{'start_line': p.span.start_line, 'end_line': p.span.end_line,
                                  'signals': p.signals} for p in c.passages]} for c in candidates]}
                with (args.output/'candidates.jsonl').open('a') as stream:
                    stream.write(json.dumps(diagnostic, ensure_ascii=False)+'\n')
                metadata['timings'].append({'id': row['id'], 'repo_id': repo,
                    'api_ms': api_ms, 'role_ms': role_ms})
            print(json.dumps({'measured': repo, 'completed': len(metadata['timings'])}), flush=True)
        finally:
            conn.close()
        write(measure/'provenance.json', metadata)
    for mode in ('api', 'role'):
        values = [r[mode+'_ms'] for r in metadata['timings']]
        metadata[mode] = {'p50_ms': float(np.percentile(values, 50)),
                         'p95_ms': float(np.percentile(values, 95)),
            'per_repo_p95_ms': {repo: float(np.percentile([
                r[mode+'_ms'] for r in metadata['timings'] if r['repo_id'] == repo], 95))
                for repo in metadata['repos']}}
    metadata['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    metadata['heavy_runtimes_imported'] = [m for m in ('torch', 'mlx', 'onnxruntime') if m in sys.modules]
    metadata['complete'] = len(metadata['timings']) == len(requests)
    write(measure/'provenance.json', metadata)
    print(json.dumps({k: metadata[k] for k in ('api', 'role', 'peak_rss_native', 'heavy_runtimes_imported')}))


if __name__ == '__main__':
    main()
