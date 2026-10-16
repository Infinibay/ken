"""Post-closure native ranking diagnosis on already exposed development only."""
from pathlib import Path
from collections import Counter
import argparse
import json

import ken
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import EntityKey
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.ranking_trace import RankingTrace
from ettin_cpu import sha
from verifiable_grading import identity_hit
from verifiable_pieces import canonical

KNOWN_DEVELOPMENT = {
    '/private/tmp/ken-verifiable-pieces-benchmark-20261015/main-cs/gold/cases.jsonl':
        'c75358d696f976d2444421dc98e9bf3bc0070dc662cedbbe288cd0a52509ed12',
    '/private/tmp/ken-verifiable-pieces-module-file-20261015/gold/cases.jsonl':
        '7297632bd221252485c79ad8a8badb450de512179366e72983247a8a8b7533ed'}


def rows(path):
    with Path(path).open() as stream:
        for line in stream:
            yield json.loads(line)


def label(unit):
    entity=unit.get('entity') or {}
    return unit['path']+('::'+entity['qualname'] if entity.get('qualname') else '')


def main():
    parser=argparse.ArgumentParser()
    for name in ('workspace','producer','diagnostics','public-cases','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    reg=json.loads((args.diagnostics/'registration.json').read_text())
    if reg['status']!='ALL200 native ranking traces closed without Gold':
        raise ValueError('ALL200 decisions must close before reference comparison')
    if verify_frozen_source(args.producer)!=reg['source_receipt']:
        raise ValueError('trace producer changed')
    for path,expected in reg['input_pins'].items():
        if sha(path)!=expected:raise ValueError('registered diagnostic input changed')
    for repo,files in reg['closed'].items():
        for name,expected in files.items():
            if sha(args.diagnostics/repo/name)!=expected:raise ValueError('trace output changed')
    if str(args.public_cases.resolve()) not in reg['input_pins']:
        raise ValueError('unregistered public query input')
    analysis_receipt=verify_frozen_source(Path(ken.__file__).resolve().parents[2])
    cases={r['id']:r for r in rows(args.public_cases)}
    if len(cases)!=200:raise ValueError('ALL200 public queries required')
    # Only the two already-exposed, fixed-hash development files may enter here.
    gold={}
    for path,expected in KNOWN_DEVELOPMENT.items():
        if sha(path)!=expected:raise ValueError('known development reference changed')
        gold.update({r['id']:r for r in rows(path)})
    if set(gold)!=set(cases):raise ValueError('development query/reference scope differs')
    args.output.mkdir(parents=True,exist_ok=False)
    analyzed=[];failures=[];leading=Counter();owners_verified=0;models={}
    for repo in reg['closed']:
        model_path=args.workspace/'output/analysis/source7-context-views-ranking-v69/contract_body251'/(repo+'-numeric.json')
        model=NumericRanker.from_dict(json.loads(model_path.read_text()))
        models[repo]={'sha256':sha(model_path),'fingerprint':model.fingerprint}
        for data in rows(args.diagnostics/repo/'ranking-traces.jsonl'):
            qid=data['id'];case=cases[qid]
            if case['repo_id']!=repo or data['query']!=case['query']:
                raise ValueError('trace/public query mismatch')
            trace=RankingTrace.from_dict(data,model)
            owners_verified+=len(data['owners'])
            acceptable=gold[qid]['acceptable_units']
            correct=next((p for p in data['pieces'] if identity_hit({'unit':p['unit']},acceptable)),None)
            rank=correct['rank'] if correct else None
            status=('top1_correct' if rank==1 else 'ranking_error_in_top10' if rank is not None and rank<=10
                    else 'ranking_error_in_top20' if rank is not None and rank<=20
                    else 'ranking_error_below_top20' if rank is not None
                    else 'no_acceptable_projected_candidate')
            selected=data['pieces'][0] if data['pieces'] else None
            row={'id':qid,'repo_id':repo,'target_kind':case['target_kind'],'language':case['language'],
                 'query':case['query'],'status':status,'correct_piece_rank':rank,
                 'selected':selected,'best_acceptable':correct,'acceptable_units':acceptable,
                 'owner_candidates':len(data['owners']),'projected_pieces':len(data['pieces'])}
            if correct is not None and rank!=1 and selected is not None:
                left=data['owners'][selected['representative_proposal_index']]
                right=data['owners'][correct['representative_proposal_index']]
                pair=trace.compare(EntityKey(path=left['path'],**left['entity']),
                                   EntityKey(path=right['path'],**right['entity']))
                row['comparison']=pair
                positives={name:delta for name,delta in pair['numeric']['branch_margin_by_feature'].items() if delta>0}
                if positives:leading[max(positives,key=positives.get)]+=1
            analyzed.append(row)
            if status!='top1_correct':failures.append(row)
    if len(analyzed)!=200 or len({r['id'] for r in analyzed})!=200:
        raise ValueError('incomplete or duplicate trace analysis')
    counts=Counter(r['status'] for r in analyzed)
    summary={'scope':'ALL200 exposed development, native ranking explanation only; identity, not joint evidence or acceptance',
        'queries':200,'identity_top1':counts['top1_correct'],
        'recall10':sum(r['correct_piece_rank'] is not None and r['correct_piece_rank']<=10 for r in analyzed),
        'recall20':sum(r['correct_piece_rank'] is not None and r['correct_piece_rank']<=20 for r in analyzed),
        'status_counts':dict(counts),'owner_scores_and_order_verified':owners_verified,
        'leading_positive_first_divergent_split_frequency':dict(leading.most_common()),
        'by_kind':{kind:dict(Counter(r['status'] for r in analyzed if r['target_kind']==kind))
                   for kind in ('class','module','symbol','file')},
        'pins':{'capture_registration_sha256':sha(args.diagnostics/'registration.json'),
                'analysis_source_receipt':analysis_receipt,'models':models,
                'known_exposed_development_gold':KNOWN_DEVELOPMENT},
        'limits':'Tree-difference accounting explains this forest decision, not causal feature importance. Scores are interpreted within each query/model. No weight, criterion, query or reference changed.'}
    for name,values in [('all-cases.jsonl',analyzed),('failures.jsonl',failures)]:
        (args.output/name).write_text(''.join(canonical(r)+'\n' for r in values))
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))
    text=['# Por qué Ken eligió otro primer resultado','',
          f'ALL200 desarrollo: identidad top1 **{summary["identity_top1"]}/200**, '
          f'Recall10 **{summary["recall10"]}/200**. Sin cambios de ranking ni criterios.',
          '',f'{owners_verified} puntuaciones y orden de candidatos reproducidos desde los valores capturados.',
          '', 'Los márgenes se interpretan dentro de cada consulta/modelo. La contribución de un árbol se agrupa por su primera rama divergente; no es un peso fijo ni una importancia causal.',
          '', '| Tipo de fallo | Casos |','|---|---:|',
          *[f'| {name} | {count} |' for name,count in counts.items() if name!='top1_correct'],'']
    for row in failures:
        text += [f'## {row["id"]} · {row["target_kind"]}', '', row['query'], '',
                 '**Elegido:** '+(label(row['selected']['unit']) if row['selected'] else 'Sin resultado'), '',
                 '**Aceptable:** '+(label(row['best_acceptable']['unit'])+f' · posición {row["correct_piece_rank"]}'
                                    if row['best_acceptable'] else 'No aparece entre las piezas candidatas proyectadas'), '']
        if 'comparison' not in row:
            text += ['No hay un par de candidatos observable para atribuir un margen numérico.','']
            continue
        pair=row['comparison'];numeric=pair['numeric']
        text += [f'Orden decidido por: `{pair["ordering_reason"]}`. Puntajes: '
                 f'{numeric["left_score"]:.6f} frente a {numeric["right_score"]:.6f}; margen {numeric["margin"]:.6f}.','',
                 '| Señal que separó ramas | Elegido | Aceptable | Margen de esos árboles |',
                 '|---|---:|---:|---:|']
        differences={f['feature']:f for f in pair['differing_features']}
        for feature,delta in sorted(numeric['branch_margin_by_feature'].items(),key=lambda r:-abs(r[1]))[:8]:
            values=differences[feature]
            text.append(f'| {feature} | {values["left"]:.6g} | {values["right"]:.6g} | {delta:+.6f} |')
        text += ['', 'Valores de todas las señales, entradas de recuperación y caminos completos por árbol: `failures.jsonl`.', '']
    (args.output/'report.md').write_text('\n'.join(text))
    print(json.dumps({k:summary[k] for k in ('queries','identity_top1','recall10','recall20','status_counts',
                                            'owner_scores_and_order_verified','leading_positive_first_divergent_split_frequency')},indent=2))


if __name__=='__main__':main()
