"""Prepared-index CPU measurements: full public requests, no cached query answers."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import ken
import sys
import time
from pathlib import Path

import numpy as np

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.source_receipts import verify_frozen_source
from ken.db import connect
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import RetrievalProfile
from ken.retrieval.service import search


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--control-model-path', type=Path)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    dataset = load_dataset(base/'datasets/development.jsonl')
    roots = {k:Path(v) for k,v in json.loads((base/'datasets/roots-development.json').read_text()).items()}
    profile = RetrievalProfile.from_dict(json.loads((args.original/'profile.json').read_text()))
    encoders = None
    if profile.behavior.backend == 'provided':
        from experimental_encoders import PotionControl
        encoder = PotionControl(args.control_model_path)
        if encoder.spec != profile.behavior or encoder.spec != profile.identity:
            raise ValueError('prepared profile/control encoder mismatch')
        encoders = {'identity':encoder, 'behavior':encoder}
    args.output.mkdir(parents=True, exist_ok=False)
    responses, timings = [], []
    connections = {}
    try:
        for repo in sorted(roots):
            connections[repo] = connect(args.original/'indices'/f'{repo}.db')
            # Loads this project's immutable source/vector/statistic views;
            # not a benchmark query and no benchmark answer is cached.
            search(connections[repo], roots[repo], SearchRequest('warm CPU source index before timed queries'),
                   profile=profile, encoders=encoders)
            for case in (c for c in dataset if c['repo_id'] == repo):
                started = time.perf_counter()
                try:
                    response = search(connections[repo], roots[repo],
                        SearchRequest(**request_for_case(case)), profile=profile, encoders=encoders).to_dict()
                    json.dumps(response, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    response = {'results':[], 'error':f'{type(exc).__name__}: {exc}'}
                timings.append({'id':case['id'], 'repo_id':repo,
                                'ms':(time.perf_counter()-started)*1000})
                responses.append({'id':case['id'], **response})
        report = evaluate(dataset, responses, roots=roots)
        (args.output/'responses.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in responses))
        (args.output/'report.json').write_text(json.dumps(report, indent=2))
        metadata = {'dataset_sha256':dataset.sha256, 'profile_sha256':profile.fingerprint,
            'source_receipt_sha256':verify_frozen_source(Path(ken.__file__).resolve().parents[2]),
            'harness_receipt_sha256':verify_frozen_source(base.parents[1]),
            'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'indexed_files':{repo:int(conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]) for repo,conn in connections.items()}, 'source_indices':str(args.original),
            'device':'cpu','platform':platform.platform(),'machine':platform.machine(),'python':sys.version,
            'timings':timings,'scope':'API + JSON serialization, prepared index; not CLI/MCP transport',
            'p50_ms':float(np.percentile([t['ms'] for t in timings],50)),
            'p95_ms':float(np.percentile([t['ms'] for t in timings],95)),
            'per_repo_p95_ms':{repo:float(np.percentile([t['ms'] for t in timings if t['repo_id']==repo],95)) for repo in roots}}
        (args.output/'performance.json').write_text(json.dumps(metadata,indent=2))
        print(json.dumps({k:metadata[k] for k in ('p50_ms','p95_ms','per_repo_p95_ms')}))
        print(json.dumps({k:report[k] for k in ('strict_top1','identity_top1')}))
    finally:
        for conn in connections.values():conn.close()


if __name__ == '__main__':
    main()
