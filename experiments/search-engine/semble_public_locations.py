"""Observe unchanged native rank positions before the public evidence budget."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import resource
import subprocess
import sys
from pathlib import Path


def project(matches, target):
    results, seen = [], set()
    for match in matches:
        path = match.entity.path
        if target == 'file' and path in seen:
            continue
        seen.add(path)
        results.append({'path': path, 'entity': match.entity.to_dict(),
            'entity_span': match.evidence[0].entity_span.to_dict(), 'source_hash': match.source_hash})
        if len(results) == 10:
            break
    return {'results': results}


def identities(response):
    return [(row['path'], row['entity']) for row in response['results']]


def worker(args):
    import ken
    from ken.bench.ranking_controls import prefer_requested_role
    from ken.bench.source_receipts import verify_frozen_source
    from ken.bench.static_embeddings import StaticEmbeddingControl
    from ken.db import connect
    from ken.retrieval.candidates import retrieve
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.profile import RetrievalProfile
    from ken.retrieval.ranking import rank_candidates

    actual = Path(ken.__file__).resolve().parents[2]
    if actual != args.engine_root.resolve():
        raise ValueError('wrong engine source')
    receipt = verify_frozen_source(actual)
    source = args.run/'ken'/args.repo
    metadata = json.loads((source/'provenance.json').read_text())
    if metadata['engine_receipt_sha256'] != receipt or not metadata['complete']:
        raise ValueError('different or incomplete source index')
    registration = json.loads(args.registration.read_text())
    model = next(r for r in registration if r['model_id'] == 'minishlab/potion-code-16M-v2')
    encoder = StaticEmbeddingControl(Path(model['root']), model)
    profile = RetrievalProfile(encoder.spec, encoder.spec)
    if profile.fingerprint != metadata['profile_sha256']:
        raise ValueError('different prepared profile')
    encoders = {'identity': encoder, 'behavior': encoder}
    requests = [json.loads(line) for line in (args.run/'requests'/f'{args.repo}.jsonl').read_text().splitlines()]
    if any(set(r) != {'id', 'repo_id', 'repo_commit', 'root', 'query'} for r in requests):
        raise ValueError('public-only request required')
    original = {r['id']: r for r in json.loads((source/'responses.json').read_text())}
    conn = connect(source/'source.db')
    responses = []
    try:
        for row in requests:
            request = SearchRequest(row['query'])
            candidates = retrieve(conn, Path(row['root']), request, profile, encoders=encoders)
            ranked = rank_candidates(request, candidates)
            role = prefer_requested_role(request, ranked)
            modes = {f'ken-{target}-{order}': project(matches, target)
                for order, matches in (('api', ranked), ('role', role))
                for target in ('symbol', 'file')}
            for mode, value in modes.items():
                before, after = identities(original[row['id']]['modes'][mode]), identities(value)
                if before != after[:len(before)]:
                    raise ValueError(f'presentation-only prefix parity failed: {row["id"]} {mode}')
            responses.append({'id': row['id'], 'modes': modes})
        if conn.total_changes:
            raise ValueError('prepared source index changed')
    finally:
        conn.close()
    payload = {'responses': responses, 'prefix_parity_checks': 4*len(responses),
        'source_receipt_sha256': receipt, 'profile_sha256': profile.fingerprint,
        'producer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'peak_main_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'heavy_modules_loaded': [n for n in ('torch', 'transformers', 'mlx') if n in sys.modules]}
    path = args.output/f'{args.repo}.json'
    with path.open('x') as stream:
        json.dump(payload, stream, ensure_ascii=False)


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    requests = [json.loads(line) for line in (args.run/'requests.jsonl').read_text().splitlines()]
    def execute(repo):
        command = [sys.executable, str(Path(__file__).resolve()), 'worker', '--repo', repo,
            '--run', str(args.run), '--engine-root', str(args.engine_root),
            '--registration', str(args.registration), '--output', str(args.output)]
        with (args.output/f'{repo}.log').open('x') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(json.dumps({'completed': repo}), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(execute, sorted({r['repo_id'] for r in requests})))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('run', 'worker'))
    parser.add_argument('--repo')
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--engine-root', type=Path, required=True)
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    {'run': run, 'worker': worker}[args.action](args)


if __name__ == '__main__':
    main()
