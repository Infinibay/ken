"""Strict external-tool scoring, kept separate from the public-query producer."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.external_results import OwnerLookup, normalize
from ken.bench.retrieval import _visible_lines, evaluate
from ken.db import connect
from ken.retrieval.storage import load_passage_map


def main():
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path)
    parser.add_argument('--canonical-indices',type=Path,required=True)
    parser.add_argument('--protocol',type=Path)
    args=parser.parse_args()
    base=Path(__file__).resolve().parent
    dataset=load_dataset(base/'datasets/development.jsonl');cases={c['id']:c for c in dataset}
    roots={k:Path(v) for k,v in json.loads((base/'datasets/roots-development.json').read_text()).items()}
    rows=[json.loads(l) for l in (args.run/'raw-responses.jsonl').read_text().splitlines()]
    if len(rows)!=len(cases) or len({r['id'] for r in rows})!=len(rows) or {r['id'] for r in rows}!=cases.keys():
        raise ValueError('all 400 unique planned responses required before comparison')
    responses=[];diagnostics=[]
    for repo in sorted(roots):
        conn=connect(args.canonical_indices/f'{repo}.db')
        owners=OwnerLookup(load_passage_map(conn).values());conn.close()
        for row in (r for r in rows if r['repo_id']==repo):
            case=cases[row['id']]
            if row['native']['query']!=case['query'] or case['repo_id']!=repo:
                raise ValueError('producer query/root record differs from frozen public input')
            normalized=normalize(row['native'],roots[repo],owners)
            responses.append({'id':row['id'],**normalized})
            first=normalized['results'][0] if normalized['results'] else None
            file_hit=bool(first and any(a['path']==first['path'] for a in case['alternatives']))
            all_anchors=False
            if first:
                try:visible=_visible_lines(first,roots[repo])
                except (ValueError,OSError,UnicodeError,TypeError,KeyError):visible=set()
                all_anchors=any(a['path']==first['path'] and all(set(range(s['start_line'],s['end_line']+1))<=visible
                    for s in a['anchors']) for a in case['alternatives'])
            diagnostics.append({'id':row['id'],'file_top1':file_hit,'visible_anchors_top1_ignoring_owner':all_anchors,
                'owner_resolved':bool(first and first['entity'] is not None),
                'invalid_evidence':bool(first and first['stale'])})
    (args.run/'responses.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in responses))
    report=evaluate(dataset,responses,roots=roots)
    (args.run/'report.json').write_text(json.dumps(report,indent=2))
    import ken.bench.external_results as adapter
    import ken.bench.retrieval as scorer
    audit={'dataset_sha256':dataset.sha256,
        'raw_responses_sha256':hashlib.sha256((args.run/'raw-responses.jsonl').read_bytes()).hexdigest(),
        'normalized_responses_sha256':hashlib.sha256((args.run/'responses.jsonl').read_bytes()).hexdigest(),
        'adapter_sha256':hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest(),
        'scorer_sha256':hashlib.sha256(Path(scorer.__file__).read_bytes()).hexdigest(),
        'protocol_sha256':hashlib.sha256((args.protocol or base/'semble-400-protocol-v1.md').read_bytes()).hexdigest(),
        'scoring_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'file_top1':sum(r['file_top1'] for r in diagnostics),
        'visible_anchors_top1_ignoring_owner':sum(r['visible_anchors_top1_ignoring_owner'] for r in diagnostics),
        'owner_resolved_top1':sum(r['owner_resolved'] for r in diagnostics),
        'invalid_evidence_top1':sum(r['invalid_evidence'] for r in diagnostics),'planned':400,'rows':diagnostics}
    (args.run/'normalization-audit.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps({k:report[k] for k in ('strict_top1','identity_top1','macro_repo_top1','strata')}))
    print(json.dumps({k:v for k,v in audit.items() if k!='rows'}))


if __name__=='__main__':main()
