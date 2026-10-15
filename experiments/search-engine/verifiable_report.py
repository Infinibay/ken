"""Post-seal audit only. This is the sole controller allowed to read new Gold."""
from __future__ import annotations
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from ettin_cpu import sha
from verifiable_grading import identity_hit,blind_pass,summarize,cluster_difference


def read_rows(path):return [json.loads(x) for x in Path(path).read_text().splitlines()]


def main():
    p=argparse.ArgumentParser()
    for name in ('public-cases','comparison','blind-inputs','judgment-seal','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--gold',type=Path,nargs='+',required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    comparison=json.loads((a.comparison/'registration.json').read_text())
    if comparison.get('status')!='ALL outputs closed without Gold or quality grading':
        raise ValueError('comparison has not closed')
    for arm,repos in comparison['closed_workers'].items():
        for repo,files in repos.items():
            for filename,expected in files.items():
                if sha(a.comparison/arm/repo/filename)!=expected:
                    raise ValueError('closed worker output changed')
    blind=json.loads((a.blind_inputs/'receipt.json').read_text())
    if blind['comparison_registration_sha256']!=sha(a.comparison/'registration.json'):
        raise ValueError('blind inputs differ from closed outputs')
    seal=json.loads(a.judgment_seal.read_text())
    if seal['status']!='ALL principal blind judgments closed before Gold':
        raise ValueError('all judgments must seal before any Gold read')
    judgments={}
    for filename,expected in seal['judgment_files'].items():
        if sha(filename)!=expected:raise ValueError('judgments changed')
        for row in read_rows(filename):
            if row['judge_id'] in judgments:raise ValueError('duplicate judge id')
            judgments[row['judge_id']]=row
    inputs={}
    for filename,expected in blind['files'].items():
        if sha(a.blind_inputs/filename)!=expected:raise ValueError('blind input changed')
        if filename!='mapping.jsonl':inputs.update({r['judge_id']:r for r in read_rows(a.blind_inputs/filename)})
    if set(inputs)!=set(judgments):raise ValueError('missing/unexpected principal judgments')
    if seal['blind_input_receipt_sha256']!=sha(a.blind_inputs/'receipt.json'):
        raise ValueError('judgment seal bound to other inputs')
    cases={r['id']:r for r in read_rows(a.public_cases)}
    if sha(a.public_cases)!=comparison['public_cases_sha256']:raise ValueError('cases changed')
    # All model outputs and all blind judgments are now verified closed.
    # No Gold byte was opened above this boundary.
    gold={}
    for path in a.gold:
        for row in read_rows(path):
            if row['id'] in gold:raise ValueError('duplicate Gold id')
            gold[row['id']]=row
    if set(gold)!=set(cases):raise ValueError('Gold/case scope differs')
    from verifiable_pieces import digest
    for qid,case in cases.items():
        if gold[qid]['public_case_sha256']!=digest(case):raise ValueError('Gold public-row hash mismatch')
    mapping={(r['arm'],r['id']):r for r in read_rows(a.blind_inputs/'mapping.jsonl')}
    results={};all_rows={}
    for arm in comparison['closed']:
        answers={r['id']:r for r in read_rows(a.comparison/arm/'answers.jsonl')}
        if sha(a.comparison/arm/'answers.jsonl')!=comparison['closed'][arm]['answers_sha256']:
            raise ValueError('answers changed')
        pools={}
        for file in (a.comparison/'baseline').glob('*/pools.jsonl'):
            pools.update({r['id']:r for r in read_rows(file)})
        rows=[]
        for qid,case in cases.items():
            accepted=gold[qid]['acceptable_units'];answer=answers[qid];card=answer['card']
            link=mapping[(arm,qid)];judge=judgments[link['judge_id']]
            identity=identity_hit(card,accepted)
            visible=blind_pass(card,case['facets'],judge)
            available=pools[qid]['cards']
            rows.append({'id':qid,'repo_id':case['repo_id'],'target_kind':case['target_kind'],
                'language':case['language'],'query_style':case['query_style'],
                'recall10':any(identity_hit(c,accepted) for c in available[:10]),
                'recall20':any(identity_hit(c,accepted) for c in available),
                'identity':identity,'blind_verifiable':visible,
                'joint':identity and visible and link['source_valid'],
                'abstain':bool(judge.get('abstain',False)),'judge_id':link['judge_id']})
        all_rows[arm]=rows
        result={'overall':summarize(rows)}
        for dimension in ('target_kind','language','query_style','repo_id'):
            result[dimension]={name:summarize([r for r in rows if r[dimension]==name])
                               for name in sorted({r[dimension] for r in rows})}
        perf=json.loads((a.comparison/arm/'performance.json').read_text())
        timings=perf['timings']
        def latency(group):
            values=[r['ms'] for r in group]
            return {'queries':len(values),'p50_ms':float(np.median(values)),
                'p95_ms':float(np.quantile(values,.95)),'max_ms':float(max(values)),
                'common_pool_p50_ms':float(np.median([r['pool_ms'] for r in group])),
                'reranker_p50_ms':float(np.median([r.get('token_ms',0)+r.get('inference_ms',0) for r in group]))}
        result['cpu']={'overall':latency(timings),
            'target_kind':{kind:latency([r for r in timings if r['target_kind']==kind])
                           for kind in ('class','module','symbol','file')},
            'processes':perf['processes'],
            'peak_rss_max_bytes':max(r['peak_rss_native']*(1 if r['rss_unit']=='bytes' else 1024)
                                     for r in perf['processes']),
            'scope':'serial prepared complete experimental typed-card pipeline; not production default API'}
        result['calibration_gate_passed']=bool(seal['calibration_gate_passed'])
        result['unlisted_alternatives_for_source_audit']=[r['id'] for r in rows
            if r['blind_verifiable'] and not r['identity']]
        result['goals_met']=bool(seal['calibration_gate_passed'] and result['overall']['recall10']['rate']>=.95
                                  and result['overall']['joint']['rate']>=.9)
        results[arm]=result
        (a.output/(arm+'-rows.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    for arm in (name for name in results if name!='baseline'):
        results[arm]['versus_baseline']={k:cluster_difference(all_rows[arm],all_rows['baseline'],key=k)
                                      for k in ('identity','joint')}
    report={'protocol':'cpu-verifiable-pieces-v98','queries':len(cases),'arms':results,
        'limitations':['New descriptive corpus, not private acceptance or Semble NDCG.',
            'Cross-curator persistent blind contexts; only current-card citations count.',
            'Recall identity coverage and card sufficiency are separate.',
            'Wilson intervals are descriptive; aggregate differences use eight repository clusters.'],
        'inputs':{'comparison':sha(a.comparison/'registration.json'),'blind':sha(a.blind_inputs/'receipt.json'),
                  'judgment_seal':sha(a.judgment_seal),'gold':{str(p):sha(p) for p in a.gold}}}
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({arm:{'identity':r['overall']['identity'],'joint':r['overall']['joint']} for arm,r in results.items()}))


if __name__=='__main__':main()
