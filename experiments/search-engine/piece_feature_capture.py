"""Capture complete typed-piece features, serially, with no reference access."""
import argparse
import gc
import json
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import time

import ken
import numpy as np
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.retrieval.candidates import owner_passages
from ken.retrieval.model import SearchRequest
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.piece_ranking import PIECE_FEATURES, piece_features
from piece_candidates import candidates_from_trace
from verifiable_pieces import SourceCatalog, canonical
from verifiable_guard import verify_source_preparation
from ettin_cpu import sha


def main():
    parser = argparse.ArgumentParser()
    for name in ('workspace', 'capture', 'source-metadata', 'public-cases', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repo')
    args = parser.parse_args(); w = args.workspace
    roots, preparation = verify_source_preparation(w, args.source_metadata)
    engine = Path(ken.__file__).resolve().parents[2]
    receipt = verify_frozen_source(engine)
    capture = json.loads((args.capture / 'registration.json').read_text())
    assert capture['status'] == 'ALL200 native ranking traces closed without Gold'
    for repo, files in capture['closed'].items():
        assert sha(args.capture / repo / 'ranking-traces.jsonl') == files['ranking-traces.jsonl']
    args.output.mkdir(exist_ok=False, parents=True)
    if args.repo is None:
        registration = {'scope': 'ALL200 public-only whole-piece features; fixed native top10 membership; no Gold',
            'source_receipt': receipt, 'preparation': preparation, 'features': list(PIECE_FEATURES),
            'capture_sha256': sha(args.capture / 'registration.json'), 'public_cases_sha256': sha(args.public_cases),
            'status': 'registered before feature capture', 'closed': {}}
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        for repo in sorted(roots):
            cmd = [sys.executable, __file__, '--workspace', str(w), '--capture', str(args.capture),
                '--source-metadata', str(args.source_metadata), '--public-cases', str(args.public_cases),
                '--output', str(args.output / repo), '--repo', repo]
            with (args.output / (repo + '.log')).open('w') as log:
                subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
            registration['closed'][repo] = {name: sha(args.output / repo / name) for name in
                ('features.npz', 'candidates.jsonl', 'performance.json')}
            print(json.dumps({'repo': repo, 'features_closed': True}), flush=True)
        assert verify_frozen_source(engine) == receipt
        registration['status'] = 'ALL200 typed piece features closed without Gold'
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        return
    repo = args.repo
    cases = {r['id']: r for r in map(json.loads, args.public_cases.read_text().splitlines())}
    static = next(r for r in json.loads((w / 'output/models/static-comparison-registration.json').read_text())
                  if r['model_id'] == 'minishlab/potion-code-16M-v2')
    encoder = StaticEmbeddingControl(Path(static['root']), static)
    index = w / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db')
    conn = sqlite3.connect(f'file:{index}?mode=ro', uri=True); conn.row_factory = sqlite3.Row
    catalog = SourceCatalog(roots[repo], owner_passages(conn))
    cache = {}; arrays = []; qids = []; rows = []; timings = []
    for line in (args.capture / repo / 'ranking-traces.jsonl').open():
        data = json.loads(line); case = cases[data['id']]
        assert data['query'] == case['query'] and data['target_kind'] == case['target_kind']
        started = time.perf_counter()
        pieces = candidates_from_trace(data, catalog, cache)
        request = SearchRequest(case['query'], piece_kind=case['target_kind'])
        features = piece_features(request, pieces, encoder=encoder, stem_words=EvidenceReranker.stem_words,
                                  expanded_query=data['expanded_query'])
        elapsed = (time.perf_counter() - started) * 1000
        arrays.append(features.values); qids.extend([case['id']] * len(pieces))
        rows.extend({'id': case['id'], 'repo_id': repo, 'target_kind': case['target_kind'],
                     'native_rank': i+1, 'unit': p['unit'],
                     'exact': max((data['owners'][j]['signals'].get('exact', 0)
                                   for j in p['owner_proposal_indices']), default=0)}
                    for i, p in enumerate(data['pieces'][:10]))
        timings.append({'id': case['id'], 'ms': elapsed})
    assert set(qids) == {qid for qid, case in cases.items() if case['repo_id'] == repo}
    np.savez_compressed(args.output / 'features.npz', x=np.concatenate(arrays), qid=np.array(qids))
    (args.output / 'candidates.jsonl').write_text(''.join(canonical(r) + '\n' for r in rows))
    (args.output / 'performance.json').write_text(json.dumps({'timings': timings,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'scope': 'piece-feature stage with cached prepared source, not complete search latency'}, indent=2))
    conn.close(); del cache, catalog; gc.collect()
    assert verify_frozen_source(engine) == receipt


if __name__ == '__main__':
    main()
