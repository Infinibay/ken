"""Score separate public calibration cards with the same fixed CPU adapters.

No labels are an input. These are scalar-calibration scores, not pipeline timing.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

from ken.retrieval.candidates import owner_passages
from ken.retrieval.query_expansion import LocalQueryExpansion
from ettin_cpu import CPUReranker,sha
from verifiable_guard import verify_source_preparation
from verifiable_pieces import SourceCatalog,card_text,digest,validate_card


def rows(path):return [json.loads(x) for x in Path(path).read_text().splitlines()]


def main():
    p=argparse.ArgumentParser()
    for name in ('workspace','source-metadata','output'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--cases',type=Path,nargs='+',required=True)
    p.add_argument('--cards',type=Path,nargs='+',required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    roots,preparation=verify_source_preparation(a.workspace,a.source_metadata)
    cases=[r for path in a.cases for r in rows(path)]
    cards=[r for path in a.cards for r in rows(path)]
    bycase={r['id']:r for r in cases}
    if len(bycase)!=20 or len(cases)!=20 or len(cards)!=60 or len({r['card_id'] for r in cards})!=60:
        raise ValueError('twenty separate calibration families / sixty cards required')
    for repo in sorted({r['repo_id'] for r in cases}):
        index=a.workspace/'output/analysis/c-source-reindex-v66c/indices'/(repo+'.db')
        conn=sqlite3.connect(f'file:{index}?mode=ro',uri=True);conn.row_factory=sqlite3.Row
        catalog=SourceCatalog(roots[repo],owner_passages(conn))
        for row in cards:
            case=bycase[row['case_id']]
            if case['repo_id']==repo:
                validate_card(row['card'],catalog)
                if row['card']['unit']['target_kind']!=case['target_kind']:
                    raise ValueError('calibration card kind differs from public request')
        conn.close()
    tr=json.loads((a.workspace/'output/models/es-en-cpu-registration-v21.json').read_text())
    expansion=LocalQueryExpansion(Path(tr['root']),tr)
    expanded={qid:expansion(case['query']) for qid,case in bycase.items()}
    receipt={'scope':'public calibration scalar scores only, no Gold/fit; not pipeline latency/RAM',
        'preparation':preparation,'public_inputs':{str(path):sha(path) for path in a.cases+a.cards},
        'script_sha256':sha(__file__),'models':{}}
    for size in ('17m','32m','68m'):
        reg=a.workspace/'output/models/ettin-all-onnx-v98'/size/'assembly.json'
        model=CPUReranker(json.loads(reg.read_text()));output=[]
        for qid,case in bycase.items():
            selected=[r for r in cards if r['case_id']==qid]
            if len(selected)!=3:raise ValueError('expected three variants per family')
            scores,details=model.score(expanded[qid],[card_text(r['card']) for r in selected])
            for row,score in zip(selected,scores,strict=True):
                output.append({'case_id':qid,'card_id':row['card_id'],
                    'card_sha256':digest(row['card']),'expanded_query':expanded[qid],'score':score})
        path=a.output/(size+'-scores.jsonl');path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in output))
        receipt['models'][size]={'registration_sha256':sha(reg),'scores_sha256':sha(path)}
        del model
    receipt['heavy_imports']=[m for m in ('torch','transformers','sentence_transformers') if m in sys.modules]
    if receipt['heavy_imports']:raise ValueError('heavy inference runtime imported')
    (a.output/'registration.json').write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
