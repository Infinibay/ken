"""Public-input CPU API worker; scoring and held-out labels stay outside it."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from pathlib import Path

import ken

from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect
from ken.retrieval.model import SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.profile import EvidenceRanking, RetrievalProfile
from ken.retrieval.query_expansion import LocalQueryExpansion
from ken.retrieval.service import search


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--requests', type=Path, required=True)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--numeric-model', type=Path, required=True)
    parser.add_argument('--static-registration', type=Path, required=True)
    parser.add_argument('--translation-registration', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.requests.read_text().splitlines()]
    if (not rows or any(set(r) != {'id', 'repo_id', 'request'} for r in rows)
            or len({r['id'] for r in rows}) != len(rows)
            or len({r['repo_id'] for r in rows}) != 1):
        raise ValueError('unique public requests from one repository required')
    args.output.mkdir(parents=True, exist_ok=False)
    engine_root = Path(ken.__file__).resolve().parents[2]
    receipt = verify_frozen_source(engine_root)
    registration = next(r for r in json.loads(args.static_registration.read_text())
                        if r['model_id'] == 'minishlab/potion-code-16M-v2')
    encoder = StaticEmbeddingControl(Path(registration['root']), registration)
    tr = json.loads(args.translation_registration.read_text())
    expansion = LocalQueryExpansion(Path(tr['root']), tr)
    model = NumericRanker.from_dict(json.loads(args.numeric_model.read_text()))
    ranker = EvidenceReranker(model, encoder, expand_query=expansion,
                             expansion_revision=expansion.revision)
    profile = RetrievalProfile(encoder.spec, encoder.spec,
        evidence=EvidenceRanking(model.fingerprint, encoder.spec, expansion.revision))
    metadata = {'scope': 'full search API + canonical JSON serialization, prepared index; CPU',
        'engine_root': str(engine_root), 'engine_receipt_sha256': receipt,
        'requests_sha256': sha(args.requests), 'numeric_model_sha256': sha(args.numeric_model),
        'profile': profile.to_dict(), 'profile_sha256': profile.fingerprint,
        'encoder': encoder.identity, 'expansion': expansion.identity,
        'python': sys.version, 'platform': platform.platform(), 'machine': platform.machine(),
        'index': str(args.index), 'root': str(args.root), 'timings': []}
    (args.output/'registration.json').write_text(json.dumps(metadata, indent=2))
    conn = connect(args.index)
    try:
        metadata['indexed_files'] = conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]
        encoders = {'identity': encoder, 'behavior': encoder}
        cold = time.perf_counter()
        search(conn, args.root, SearchRequest('prepare CPU source index for search'),
               profile=profile, encoders=encoders, owner_ranker=ranker)
        metadata['source_prepare_ms'] = (time.perf_counter()-cold)*1000
        with (args.output/'responses.jsonl').open('w') as output:
            for row in rows:
                request = SearchRequest(**row['request'])
                started = time.perf_counter()
                try:
                    response = search(conn, args.root, request, profile=profile,
                                      encoders=encoders, owner_ranker=ranker).to_dict()
                    json.dumps(response, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    response = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
                metadata['timings'].append({'id': row['id'], 'ms': (time.perf_counter()-started)*1000})
                output.write(json.dumps({'id': row['id'], **response}, ensure_ascii=False)+'\n')
                output.flush()
        metadata['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if verify_frozen_source(engine_root) != receipt:
            raise ValueError('engine source changed during the run')
        (args.output/'performance.json').write_text(json.dumps(metadata, indent=2))
        print(json.dumps({'repo': rows[0]['repo_id'], 'queries': len(rows),
                          'peak_rss_native': metadata['peak_rss_native']}), flush=True)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
