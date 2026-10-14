"""CPU candidate-coverage diagnostic using literal public-query facets only."""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from dataclasses import replace
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import request_for_case
from ken.bench.query_expansion import facet_queries, combine_proposals
from ken.bench.source_receipts import verify_frozen_source
from ken.db import connect
from ken.retrieval.candidates import retrieve
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.intent import interpret
from ken.retrieval.model import SearchRequest
from ken.retrieval.profile import RetrievalProfile


def main():
    p = argparse.ArgumentParser()
    p.add_argument('original',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--control-model-path',type=Path)
    p.add_argument('--limit',type=int,default=50)
    p.add_argument('--width',type=int,default=8)
    p.add_argument('--max-facets',type=int,default=6)
    p.add_argument('--primary-quota',type=int,default=50)
    args = p.parse_args()
    base=Path(__file__).resolve().parent
    dataset=load_dataset(base/'datasets/development.jsonl')
    cases=list(dataset)[:args.limit]
    roots={k:Path(v) for k,v in json.loads((base/'datasets/roots-development.json').read_text()).items()}
    profile=RetrievalProfile.from_dict(json.loads((args.original/'profile.json').read_text()))
    original={r['id']:r for r in (json.loads(l) for l in (args.original/'candidates.jsonl').read_text().splitlines())}
    if any(c['id'] not in original for c in cases):
        raise ValueError('all planned cases require original candidate pools; none can be dropped')
    encoders=None
    if profile.behavior.backend=='provided':
        from experimental_encoders import PotionControl,E5OnnxControl
        ctor=PotionControl if profile.behavior.model_id=='minishlab/potion-code-16M-v2' else E5OnnxControl
        encoder=ctor(args.control_model_path)
        if encoder.spec != profile.behavior or encoder.spec != profile.identity:
            raise ValueError('control model must match the original index')
        encoders={'identity':encoder,'behavior':encoder}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'indices').symlink_to((args.original/'indices').resolve(),target_is_directory=True)
    records,queries,times=[],[],[]
    for repo in sorted({c['repo_id'] for c in cases}):
        conn=connect(args.original/'indices'/f'{repo}.db')
        for case in (c for c in cases if c['repo_id']==repo):
            request=SearchRequest(**request_for_case(case))
            facets=facet_queries(request,width=args.width,max_facets=args.max_facets)
            started=time.perf_counter()
            with retrieval_snapshot(conn):
                pools=[retrieve(conn,roots[repo],replace(request,query=q,purpose=interpret(request).purpose),
                                profile,encoders=encoders) for q in facets]
                old=[(c['path'],c['entity']) for c in original[case['id']]['candidates']]
                current=[(c.entity.path,c.entity.to_dict()) for c in pools[0]]
                if current != old:
                    raise ValueError('primary pool changed before expansion')
                combined=combine_proposals(pools,limit=100,primary_quota=args.primary_quota)
            times.append((time.perf_counter()-started)*1000)
            records.append({'id':case['id'],'candidates':[{'path':c.entity.path,'entity':c.entity.to_dict(),
                'signals':c.signals,'passages':[{'start_line':x.span.start_line,'end_line':x.span.end_line,
                                              'signals':x.signals} for x in c.passages]} for c in combined]})
            queries.append({'id':case['id'],'queries':facets})
        conn.close()
        (args.output/'candidates.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
        (args.output/'public-queries.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in queries))
        print(json.dumps({'completed_repo':repo,'queries':len(records)}),flush=True)
    (args.output/'profile.json').write_text(json.dumps(profile.to_dict(),indent=2))
    (args.output/'provenance.json').write_text(json.dumps({'dataset_sha256':dataset.sha256,
        'source_receipt_sha256':verify_frozen_source(base.parents[1]),
        'original_pool_sha256':hashlib.sha256((args.original/'candidates.jsonl').read_bytes()).hexdigest(),
        'case_ids':[c['id'] for c in cases],'profile_sha256':profile.fingerprint,
        'width':args.width,'max_facets':args.max_facets,'primary_quota':args.primary_quota,
        'rrf_weights':'primary0.5; expansion0.5 divided equally among literal facets',
        'limit':100,'timings_ms':times,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'scope':'candidate coverage only; no strict-top1 or acceptance claim'},indent=2))


if __name__=='__main__':main()
