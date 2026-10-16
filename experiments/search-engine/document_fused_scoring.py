"""Preserve every actual stage value and the failures of a closed CPU fusion run."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from ken.retrieval.reranker_fusion import fused_reranker_order
from ettin_cpu import sha
from piece_complete_report import KNOWN, rows
from verifiable_grading import identity_hit


def label(unit):
    entity = unit['entity'] or {}
    return (unit['path'] + ':' + (entity.get('qualname') or unit.get('module_name') or '')).replace('|', '\\|')


def main():
    p = argparse.ArgumentParser()
    for name in ('capture', 'report', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    args = p.parse_args()
    registration = json.loads((args.capture / 'registration.json').read_text())
    if registration['status'] != 'ALL200 complete CPU outputs closed without Gold':
        raise ValueError('full closure required before diagnostic references')
    summary = json.loads((args.report / 'summary.json').read_text())
    if summary['registration_sha256'] != sha(args.capture / 'registration.json'):
        raise ValueError('report/capture mismatch')
    public_path = next(path for path in registration['input_pins'] if path.endswith('verifiable-pieces-v98-public/cases.jsonl'))
    if sha(public_path) != registration['input_pins'][public_path]:
        raise ValueError('public questions changed')
    public = {r['id']: r for r in rows(public_path)}
    orders = {}; answers = {}; bypass = {}; input_pins = {}
    for repo, files in registration['closed'].items():
        for name, expected in files.items():
            path = args.capture / repo / name
            if sha(path) != expected:
                raise ValueError('closed worker output differs')
            input_pins[str(path)] = expected
        orders.update({r['id']: r for r in rows(args.capture / repo / 'orders.jsonl')})
        answers.update({r['id']: r for r in rows(args.capture / repo / 'answers.jsonl')})
        perf = json.loads((args.capture / repo / 'performance.json').read_text())
        bypass.update({r['id']: r['exact_bypass'] for r in perf['timings']})
    if len(orders) != len(answers) or len(answers) != 200:
        raise ValueError('ALL200 required')
    gold = {}
    for path, expected in KNOWN.items():
        if sha(path) != expected:
            raise ValueError('fixed exposed references differ')
        gold.update({r['id']: r for r in rows(path)})
    args.output.mkdir(parents=True, exist_ok=False)
    failures = []; values = []
    for qid, answer in answers.items():
        order = orders[qid]; units = order['native_units']; accepted = gold[qid]['acceptable_units']
        scores = order['neural_scores_in_piece_order']; existing = order['piece_order']
        neural = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        if bypass[qid]:
            neural = list(range(len(scores)))
        fused = fused_reranker_order(scores) if not bypass[qid] else list(range(len(scores)))
        if fused != order['fusion_order_in_piece_order']:
            raise ValueError('actual fusion order cannot be reconstructed')
        query_values = []
        for position, native in enumerate(existing):
            neural_rank = neural.index(position) + 1
            value = {'id': qid, 'target_kind': answer['target_kind'], 'piece': label(units[native]),
                'native_rank': native + 1, 'piece_rank': position + 1,
                'prior_score': order['piece_scores'][position], 'neural_logit': scores[position],
                'neural_rank': neural_rank, 'ken_rrf_component': .5 / (61 + position),
                'neural_rrf_component': .5 / (60 + neural_rank),
                'fusion_score': .5 / (61 + position) + .5 / (60 + neural_rank),
                'final_rank': order['final_order'].index(native) + 1,
                'acceptable': identity_hit({'unit': units[native]}, accepted)}
            query_values.append(value); values.append(value)
        query_values.sort(key=lambda r: r['final_rank'])
        if identity_hit(answer['card'], accepted):
            continue
        correct = next((r for r in query_values if r['acceptable']), None)
        failures.append({'id': qid, 'target_kind': answer['target_kind'], 'correct_in_top10': correct is not None})
        text = [f'# {qid}: decisión final de la fusión', '',
            'Valores de la ejecución completa v132; no se reutilizaron logits históricos.', '',
            '> ' + public[qid]['query'].replace('\n', '\n> '), '',
            f'Pieza elegida: `{label(answer["card"]["unit"])}`.',
            f'Aceptable en top10: {"sí, puesto final" + str(correct["final_rank"]) if correct else "no; esta etapa no le calculó un score"}.', '',
            'prior_score es el bosque de piezas para clase/módulo/archivo y el score nativo del owner para símbolos. '
            'Los dos componentes RRF pesan0.5 y usan constante60; las posiciones parten de1. '
            'La prioridad de ruta explícita se aplica después y el bypass exacto conserva el orden de piezas.', '']
        if correct:
            selected = query_values[0]
            text += [f'Margen RRF elegido−aceptable: {selected["fusion_score"] - correct["fusion_score"]!r}. '
                'Es una diferencia ordinal exacta; los logits no se suman directamente al score.', '']
        for folder in ('cases', 'piece-cases'):
            if (args.output.parent / folder / (qid + '.md')).is_file():
                text += [f'[Explicación del bosque previo: {folder}](../{folder}/{qid}.md).', '']
        text += ['| Pieza | Aceptable | Nativo | Pieza | Prior score | Logit68M | Neural | RRF Ken | RRF neural | Fusión | Final |',
                 '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
        for r in query_values:
            fields = ('piece', 'acceptable', 'native_rank', 'piece_rank', 'prior_score', 'neural_logit',
                      'neural_rank', 'ken_rrf_component', 'neural_rrf_component', 'fusion_score', 'final_rank')
            text.append('| ' + ' | '.join(str(r[k]) for k in fields) + ' |')
        (args.output / (qid + '.md')).write_text('\n'.join(text) + '\n')
    if len(failures) != 200 - summary['counts']['complete']['identity']:
        raise ValueError('failure counts disagree')
    with (args.output / 'all-stage-values.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(values[0]), lineterminator='\n')
        writer.writeheader(); writer.writerows(values)
    (args.output / 'INDEX.md').write_text('# Fallos de la fusión completa v132\n\n'
        + f'{len(failures)} fallos; {sum(r["correct_in_top10"] for r in failures)} con el aceptable en top10. '
          'Cada caso conserva los valores reales de los diez candidatos; el CSV incluye las200 consultas.\n\n'
        + '\n'.join(f'- [{r["id"]}]({r["id"]}.md), {r["target_kind"]}, aceptable en top10: {r["correct_in_top10"]}.' for r in failures) + '\n')
    manifest = {'scope': 'Actual complete CPU132 stages, all200; exposed development only',
        'producer_sha256': sha(__file__), 'capture_registration_sha256': sha(args.capture / 'registration.json'),
        'summary_sha256': sha(args.report / 'summary.json'), 'input_pins': input_pins,
        'cases': 200, 'candidate_rows': len(values), 'failures': failures,
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.glob('*'))}}
    (args.output / 'VALUES-MANIFEST.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'cases': 200, 'candidate_rows': len(values), 'failures': len(failures)}))


if __name__ == '__main__':
    main()
