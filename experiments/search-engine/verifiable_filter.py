"""Offline shadow rejection policy, fitted on calibration only after blind seal."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

from ettin_cpu import sha


def conservative_threshold(scores,labels):
    protected=[]
    for row in labels:
        if row['variant'] not in {'sufficient','identity_only_insufficient','faithful_plausible_distractor'}:
            raise ValueError('unknown calibration variant')
        if row['variant']!='faithful_plausible_distractor':
            value=scores.get(row['card_id'])
            if value is None or not math.isfinite(value):raise ValueError('missing protected score')
            protected.append(value)
    if not protected:raise ValueError('no protected correct-unit calibration')
    return min(protected)


def filter_order(scores,threshold):
    if any(not math.isfinite(s) for s in scores):raise ValueError('nonfinite principal score')
    return sorted((i for i,s in enumerate(scores) if s>=threshold),key=lambda i:(-scores[i],i))


def rows(path):return [json.loads(x) for x in Path(path).read_text().splitlines()]


def main():
    p=argparse.ArgumentParser()
    for name in ('comparison','principal-judgment-seal','calibration-scores','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--calibration-gold',type=Path,nargs='+',required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    comparison=json.loads((a.comparison/'registration.json').read_text())
    seal=json.loads(a.principal_judgment_seal.read_text())
    if (comparison.get('status')!='ALL outputs closed without Gold or quality grading'
        or seal.get('status')!='ALL principal blind judgments closed before Gold'):
        raise ValueError('all principal outputs/judgments must close before calibration Gold')
    for path,value in seal['judgment_files'].items():
        if sha(path)!=value:raise ValueError('principal judgments changed')
    for arm,repos in comparison['closed_workers'].items():
        for repo,files in repos.items():
            for name,value in files.items():
                if sha(a.comparison/arm/repo/name)!=value:raise ValueError('closed output changed')
    # Only separate calibration Gold is opened. Principal Gold is not an input.
    labels=[r for path in a.calibration_gold for r in rows(path)]
    if len(labels)!=60 or len({r['card_id'] for r in labels})!=60:
        raise ValueError('all60 separate calibration cards required')
    registration={'scope':'post-blind-seal scalar calibration + offline principal shadow filter; no principal Gold',
        'policy':'min score of40 faithful correct-unit calibration cards; incomplete cards protected; inclusive cutoff',
        'principal_judgment_seal_sha256':sha(a.principal_judgment_seal),
        'comparison_sha256':sha(a.comparison/'registration.json'),
        'calibration_gold':{str(path):sha(path) for path in a.calibration_gold},
        'script_sha256':sha(__file__),'models':{}}
    for arm in ('17m','32m','68m'):
        scorefile=a.calibration_scores/(arm+'-scores.jsonl')
        scores={r['card_id']:r['score'] for r in rows(scorefile)}
        if len(scores)!=60 or set(scores)!={r['card_id'] for r in labels}:raise ValueError('calibration score scope differs')
        cutoff=conservative_threshold(scores,labels)
        protected=[r for r in labels if r['variant']!='faithful_plausible_distractor']
        if len(protected)!=40:raise ValueError('expected40 protected correct-unit cards')
        negatives=[r for r in labels if r.get('expected_relevance')==0]
        record={'threshold':cutoff,'calibration_scores_sha256':sha(scorefile),
            'protected_kept':sum(scores[r['card_id']]>=cutoff for r in protected),
            'protected':len(protected),'known_irrelevant':len(negatives),
            'known_irrelevant_discarded':sum(scores[r['card_id']]<cutoff for r in negatives)}
        output=[]
        for path in (a.comparison/arm).glob('*/pools.jsonl'):
            for row in rows(path):
                if row['scores'] is None:
                    output.append({'id':row['id'],'exact_bypass':True,'kept':row['order'],
                                   'all_rejected':False,'top_index':row['order'][0] if row['order'] else None})
                    continue
                order=filter_order(row['scores'],cutoff)
                if order and order[0]!=row['order'][0]:raise ValueError('monotonic top1 invariant failed')
                output.append({'id':row['id'],'exact_bypass':False,'kept':order,
                    'all_rejected':not bool(order),'top_index':order[0] if order else None})
        out=a.output/(arm+'-filter.jsonl');out.write_text(''.join(json.dumps(r)+'\n' for r in output))
        record['principal_shadow_sha256']=sha(out);registration['models'][arm]=record
    (a.output/'registration.json').write_text(json.dumps(registration,indent=2))


if __name__=='__main__':main()
