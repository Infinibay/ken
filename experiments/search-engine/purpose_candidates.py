"""Development coverage control: apply public purpose before the final owner budget."""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from dataclasses import replace
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.ranking_controls import select_requested_role_candidates
from ken.bench.retrieval import request_for_case
from ken.bench.source_receipts import verify_frozen_source
from ken.db import connect
from ken.retrieval.candidates import retrieve
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import RetrievalProfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--control-model-path', type=Path)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--channel-limit', type=int, default=1000)
    args = parser.parse_args()
    if args.channel_limit < 100:
        raise ValueError('channel limit must cover the final 100-owner budget')
    base = Path(__file__).resolve().parent
    dataset = load_dataset(base/'datasets/development.jsonl')
    cases = list(dataset)[:args.limit]
    roots = {k:Path(v) for k,v in json.loads((base/'datasets/roots-development.json').read_text()).items()}
    profile = RetrievalProfile.from_dict(json.loads((args.original/'profile.json').read_text()))
    original = {r['id']:r for r in (json.loads(l) for l in (args.original/'candidates.jsonl').read_text().splitlines())}
    if any(c['id'] not in original for c in cases):
        raise ValueError('every planned case requires an original pool')
    encoders = None
    if profile.behavior.backend == 'provided':
        from experimental_encoders import PotionControl, E5OnnxControl
        constructor = PotionControl if profile.behavior.model_id == 'minishlab/potion-code-16M-v2' else E5OnnxControl
        encoder = constructor(args.control_model_path)
        if encoder.spec != profile.behavior or encoder.spec != profile.identity:
            raise ValueError('control model differs from original index')
        encoders = {'identity':encoder,'behavior':encoder}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'indices').symlink_to((args.original/'indices').resolve(), target_is_directory=True)
    records, times = [], []
    expanded_profile = replace(profile, candidate_limit=args.channel_limit)
    for repo in sorted({c['repo_id'] for c in cases}):
        conn = connect(args.original/'indices'/f'{repo}.db')
        for case in (c for c in cases if c['repo_id'] == repo):
            request = SearchRequest(**request_for_case(case))
            with retrieval_snapshot(conn):
                primary = retrieve(conn, roots[repo], request, profile, encoders=encoders)
                expected = [(c['path'],c['entity']) for c in original[case['id']]['candidates']]
                if [(c.entity.path,c.entity.to_dict()) for c in primary] != expected:
                    raise ValueError('baseline pool changed before purpose selection')
                started = time.perf_counter()
                broad = retrieve(conn, roots[repo], request, expanded_profile, encoders=encoders)
                selected = select_requested_role_candidates(request, broad, limit=100)
                times.append((time.perf_counter()-started)*1000)
            records.append({'id':case['id'],'candidates':[{'path':c.entity.path,'entity':c.entity.to_dict(),
                'signals':c.signals,'passages':[{'start_line':p.span.start_line,'end_line':p.span.end_line,
                                              'signals':p.signals} for p in c.passages]} for c in selected]})
        conn.close()
        (args.output/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
        print(json.dumps({'completed_repo':repo,'queries':len(records)}),flush=True)
    (args.output/'profile.json').write_text(json.dumps(profile.to_dict(),indent=2))
    (args.output/'provenance.json').write_text(json.dumps({'dataset_sha256':dataset.sha256,
        'source_receipt_sha256':verify_frozen_source(base.parents[1]),
        'original_pool_sha256':hashlib.sha256((args.original/'candidates.jsonl').read_bytes()).hexdigest(),
        'case_ids':[c['id'] for c in cases],'profile_sha256':profile.fingerprint,
        'channel_limit':args.channel_limit,'final_owner_limit':100,
        'purpose':'derived from original public query only; no benchmark label',
        'timing_scope':'warmed public retrieve plus purpose selection, excluding baseline comparison',
        'timings_ms':times,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'scope':'development candidate coverage only; no acceptance or default claim'},indent=2))


if __name__ == '__main__':
    main()
