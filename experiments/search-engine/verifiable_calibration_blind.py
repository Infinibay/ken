"""Blind calibration cards without variant labels, scores or expected targets."""
import argparse
import json
import random
from pathlib import Path

from ettin_cpu import sha
from verifiable_pieces import canonical,digest


def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--score-registration',type=Path)
    group.add_argument('--source-registration',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    input_registration=a.source_registration or a.score_registration
    registration=json.loads(input_registration.read_text());cases={};cards=[]
    if a.source_registration and registration.get('scope')!='ALL60 public calibration cards source-authenticated; no scores or Gold':
        raise ValueError('expected complete source-authentication receipt')
    for path,expected in registration['public_inputs'].items():
        if sha(path)!=expected:raise ValueError('calibration input changed')
        values=[json.loads(x) for x in Path(path).read_text().splitlines()]
        if values and 'query' in values[0]:
            for row in values:
                if row['id'] in cases:raise ValueError('duplicate family id')
                cases[row['id']]=row
        else:cards.extend(values)
    if len(cases)!=20 or len(cards)!=60:raise ValueError('calibration scope differs')
    visible=[];mapping=[]
    for row in cards:
        case=cases[row['case_id']]
        body={k:case[k] for k in ('query','target_kind','language','facets')}
        body['card']=row['card'];judge_id='K'+digest(body)[:24]
        visible.append({'judge_id':judge_id,**body})
        mapping.append({'judge_id':judge_id,'case_id':row['case_id'],'card_id':row['card_id']})
    if len({r['judge_id'] for r in visible})!=60:raise ValueError('duplicate visible calibration variants')
    random.Random(2026101501).shuffle(visible)
    for role,kinds in [('class-symbol',{'class','symbol'}),('module-file',{'module','file'})]:
        path=a.output/(role+'.jsonl')
        path.write_text(''.join(canonical(r)+'\n' for r in visible if r['target_kind'] in kinds))
    (a.output/'mapping.jsonl').write_text(''.join(canonical(r)+'\n' for r in mapping))
    receipt={'scope':'sixty public calibration cards; no labels/scores/model identities visible',
        'input_registration_sha256':sha(input_registration),
        'input_registration_kind':'source-only' if a.source_registration else 'scalar-scores',
        'families':20,'cards':60,
        'files':{path.name:sha(path) for path in a.output.glob('*.jsonl')}}
    (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
