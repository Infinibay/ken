"""Post-closure identity comparison using the already-open development Gold."""
import argparse
import json
from pathlib import Path

from uv_release_capture import sha,read_rows
from uv_release_identity import native_units
from verifiable_grading import identity_hit,cluster_difference


def summarize(rows):
    n=len(rows)
    return {'queries':n,**{key:{'count':sum(r[key] for r in rows),
             'rate':sum(r[key] for r in rows)/n} for key in ('identity','recall10')}}


def main():
    p=argparse.ArgumentParser()
    for name in ('workspace','capture','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    reg=json.loads((a.capture/'registration.json').read_text())
    if reg['status']!='ALL200 native answers closed without Gold':
        raise ValueError('native run has not closed')
    for path,expected in reg['pins'].items():
        if sha(path)!=expected:raise ValueError('capture producer/input changed')
    for repo,files in reg['closed'].items():
        for name,expected in files.items():
            if sha(a.capture/'native'/repo/name)!=expected:raise ValueError('native output changed')
    if sha(a.capture/'native-answers.jsonl')!=reg['answers_sha256']:
        raise ValueError('aggregate native output changed')
    current=a.workspace/'output/development/verifiable-pieces-v102'
    current_reg=json.loads((current/'registration.json').read_text())
    if sha(current/'registration.json')!=reg['current_comparison_sha256']:
        raise ValueError('experimental arm registration changed')
    for repo,files in current_reg['closed_workers']['baseline'].items():
        for name,expected in files.items():
            if sha(current/'baseline'/repo/name)!=expected:raise ValueError('experimental output changed')
    public=a.workspace/'output/development/verifiable-pieces-v98-public/cases.jsonl'
    if sha(public)!=reg['public_cases_sha256']:raise ValueError('not the same queries')
    cases=read_rows(public)
    native={r['id']:r for r in read_rows(a.capture/'native-answers.jsonl')}
    pools={r['id']:r for file in (current/'baseline').glob('*/pools.jsonl') for r in read_rows(file)}
    catalog=a.workspace/'output/analysis/verifiable-pieces-catalog-v98'
    catalog_receipt=json.loads((catalog/'receipt.json').read_text())
    inventories={}
    for repo,record in catalog_receipt['repos'].items():
        path=catalog/(repo+'.jsonl')
        if sha(path)!=record['inventory_sha256']:raise ValueError('source catalog changed')
        inventories[repo]=read_rows(path)
    if len(cases)!=200 or set(native)!=set(pools) or set(native)!={c['id'] for c in cases}:
        raise ValueError('missing/duplicate case')
    # Only the Gold files pinned by the completed v102 development report may
    # be opened. The new private acceptance reserve is not an input here.
    prior_report=a.workspace/'output/development/verifiable-pieces-report-v102/report.json'
    gold_pins=json.loads(prior_report.read_text())['inputs']['gold']
    gold={}
    for path,expected in gold_pins.items():
        if sha(path)!=expected:raise ValueError('closed development Gold changed')
        for row in read_rows(path):
            if row['id'] in gold:raise ValueError('duplicate Gold')
            gold[row['id']]=row
    if set(gold)!=set(native):raise ValueError('Gold scope differs')
    rows={name:[] for name in ('published_uv','experimental_v102')}
    diagnostics=[]
    for case in cases:
        qid=case['id'];accepted=gold[qid]['acceptable_units'];record=native[qid]
        raw=record['native'] if isinstance(record['native'],list) and not record['error'] else []
        cards=native_units(raw,case['target_kind'],inventories[case['repo_id']])
        for arm,available in (('published_uv',cards),('experimental_v102',pools[qid]['cards'])):
            rows[arm].append({'id':qid,'repo_id':case['repo_id'],'target_kind':case['target_kind'],
                'language':case['language'],'query_style':case['query_style'],
                'identity':identity_hit(available[0],accepted) if available else False,
                'recall10':any(identity_hit(c,accepted) for c in available[:10])})
        diagnostics.append({'id':qid,'error':record['error'],'results':len(raw),
            'unresolved_native_positions':sum(c is None for c in cards),
            'unresolved':[{k:r.get(k) for k in ('file','kind','qualname','line','line_end')}
                          for r,c in zip(raw,cards) if c is None]})
    arms={}
    for name,values in rows.items():
        arms[name]={'overall':summarize(values)}
        for dimension in ('target_kind','language','query_style','repo_id'):
            arms[name][dimension]={k:summarize([r for r in values if r[dimension]==k])
                                  for k in sorted({r[dimension] for r in values})}
    if arms['experimental_v102']['overall']!={'queries':200,'identity':{'count':168,'rate':.84},
                                              'recall10':{'count':197,'rate':.985}}:
        raise ValueError('existing84/98.5 results did not reproduce with unchanged identity scorer')
    report={'scope':'descriptive matched ALL200 identity comparison; no evidence-sufficiency score',
        'arms':arms,'paired_difference':{key:cluster_difference(rows['experimental_v102'],
                rows['published_uv'],key=key) for key in ('identity','recall10')},
        'errors':sum(bool(d['error']) for d in diagnostics),
        'inputs':{'capture_registration':sha(a.capture/'registration.json'),
                  'experimental_registration':sha(current/'registration.json'),'public':sha(public),
                  'development_gold':gold_pins,'normalizer':sha(Path(__file__).parent/'uv_release_identity.py')},
        'limitations':['Development corpus, not the new private acceptance reserve.',
            'Published native scopes chosen once by requested piece type, not by answers.',
            'No candidates promoted, no enclosing class credited for a returned method.',
            'No source excerpts were added to published answers; evidence sufficiency remains unmeasured.',
            'Differences include the complete pipeline/models/admission, not one isolated change.']}
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    for name,values in rows.items():
        (a.output/(name+'-rows.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in values))
    (a.output/'native-resolution-audit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in diagnostics))
    print(json.dumps({'arms':{k:v['overall'] for k,v in arms.items()},'errors':report['errors']}))


if __name__=='__main__':main()
