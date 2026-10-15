"""Anonymize/de-duplicate fixed top answers, authenticate source, never read Gold."""
import argparse
import json
import random
import sqlite3
from pathlib import Path

from ken.retrieval.candidates import owner_passages
from verifiable_pieces import SourceCatalog,canonical,digest,validate_card
from ettin_cpu import sha


def main():
    p=argparse.ArgumentParser()
    for name in ('workspace','comparison','public-cases','source-metadata','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    reg=json.loads((a.comparison/'registration.json').read_text())
    if reg.get('status')!='ALL outputs closed without Gold or quality grading':
        raise ValueError('all model outputs must close before principal blind input')
    cases={c['id']:c for c in map(json.loads,a.public_cases.read_text().splitlines())}
    if sha(a.public_cases)!=reg['public_cases_sha256']:raise ValueError('public cases changed')
    arms=('baseline','17m','32m','68m');answers={}
    for arm in arms:
        path=a.comparison/arm/'answers.jsonl'
        if sha(path)!=reg['closed'][arm]['answers_sha256']:raise ValueError('answers changed')
        answers[arm]={r['id']:r for r in map(json.loads,path.read_text().splitlines())}
        if set(answers[arm])!=set(cases):raise ValueError('missing answers')
    roots=json.loads((a.source_metadata/'roots.json').read_text())
    inputs={};mapping=[]
    for repo in sorted({c['repo_id'] for c in cases.values()}):
        index=a.workspace/'output/analysis/c-source-reindex-v66c/indices'/(repo+'.db')
        conn=sqlite3.connect(f'file:{index}?mode=ro',uri=True);conn.row_factory=sqlite3.Row
        catalog=SourceCatalog(roots[repo],owner_passages(conn))
        for qid,case in cases.items():
            if case['repo_id']!=repo:continue
            for arm in arms:
                answer=answers[arm][qid];card=answer['card']
                if card:validate_card(card,catalog)
                # Identical visible query/card gets one judgment shared by every arm.
                body={k:case[k] for k in ('query','target_kind','language','facets')}
                body['card']=card
                judge_id='J'+digest(body)[:24]
                inputs[judge_id]={'judge_id':judge_id,**body}
                mapping.append({'id':qid,'arm':arm,'judge_id':judge_id,'source_valid':card is not None})
        conn.close()
    rows=list(inputs.values());random.Random(20261015).shuffle(rows)
    for role,kinds in [('class-symbol',{'class','symbol'}),('module-file',{'module','file'})]:
        path=a.output/(role+'.jsonl')
        path.write_text(''.join(canonical(r)+'\n' for r in rows if r['target_kind'] in kinds))
    (a.output/'mapping.jsonl').write_text(''.join(canonical(r)+'\n' for r in mapping))
    receipt={'comparison_registration_sha256':sha(a.comparison/'registration.json'),
        'public_cases_sha256':sha(a.public_cases),'queries':len(cases),'answers':len(mapping),
        'unique_visible_inputs':len(inputs),'seed':20261015,
        'files':{path.name:sha(path) for path in a.output.glob('*.jsonl')},
        'scope':'source-authenticated anonymized individual cards; no Gold or model labels to consumer'}
    (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt),flush=True)


if __name__=='__main__':main()
