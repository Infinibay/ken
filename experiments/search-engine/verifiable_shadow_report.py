"""Score sealed shadow selections; original200 denominator and visible evidence gates."""
import argparse
import json
from pathlib import Path

from ettin_cpu import sha
from verifiable_grading import blind_pass, cluster_difference, identity_hit, summarize


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser()
    for name in ('public-cases', 'comparison', 'principal-inputs', 'shadow-inputs', 'shadows',
                 'final-judgment-seal', 'primary-report', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    final = json.loads(args.final_judgment_seal.read_text())
    primary = json.loads((args.primary_report / 'report.json').read_text())
    comparison = json.loads((args.comparison / 'registration.json').read_text())
    shadow = json.loads((args.shadows / 'registration.json').read_text())
    principal_receipt = args.principal_inputs / 'receipt.json'
    shadow_receipt = args.shadow_inputs / 'receipt.json'
    if (final.get('status') != 'ALL primary and shadow blind judgments closed before principal Gold'
            or final['principal_input_receipt_sha256'] != sha(principal_receipt)
            or final['shadow_input_receipt_sha256'] != sha(shadow_receipt)
            or final['principal_judgment_seal_sha256'] != primary['inputs']['judgment_seal']
            or primary['inputs']['comparison'] != sha(args.comparison / 'registration.json')
            or primary['inputs']['blind'] != sha(principal_receipt)
            or shadow['comparison_sha256'] != sha(args.comparison / 'registration.json')):
        raise ValueError('final blind/primary report closures differ')
    if comparison.get('status') != 'ALL outputs closed without Gold or quality grading':
        raise ValueError('comparison must close')
    for arm, repos in comparison['closed_workers'].items():
        for repo, files in repos.items():
            for name, expected in files.items():
                if sha(args.comparison / arm / repo / name) != expected:
                    raise ValueError('original worker changed')
    inputs, mappings = {}, None
    for directory in (args.principal_inputs, args.shadow_inputs):
        receipt = json.loads((directory / 'receipt.json').read_text())
        for name, expected in receipt['files'].items():
            if sha(directory / name) != expected:
                raise ValueError('blind input changed')
            if name == 'mapping.jsonl':
                if directory == args.shadow_inputs:
                    mappings = rows(directory / name)
            else:
                for row in rows(directory / name):
                    previous = inputs.setdefault(row['judge_id'], row)
                    if previous != row:
                        raise ValueError('nonidentical input reused')
    judgments = {}
    for path, expected in final['judgment_files'].items():
        if sha(path) != expected:
            raise ValueError('final judgment changed')
        for row in rows(path):
            if row['judge_id'] in judgments:
                raise ValueError('duplicate final judgment')
            judgments[row['judge_id']] = row
    if set(inputs) != set(judgments):
        raise ValueError('missing/unexpected final judgments')
    if sha(args.public_cases) != comparison['public_cases_sha256']:
        raise ValueError('public cases changed')
    cases = {r['id']: r for r in rows(args.public_cases)}
    if len(cases) != 200:
        raise ValueError('all200 original cases required')
    # Principal Gold may be reread only after verifying the FINAL blind closure.
    gold = {}
    for path, expected in primary['inputs']['gold'].items():
        if sha(path) != expected:
            raise ValueError('principal Gold changed since original report')
        for row in rows(path):
            if row['id'] in gold:
                raise ValueError('duplicate Gold id')
            gold[row['id']] = row
    if set(gold) != set(cases):
        raise ValueError('Gold case scope differs')
    pools = {r['id']: r for p in (args.comparison / 'baseline').glob('*/pools.jsonl') for r in rows(p)}
    mapping = {(r['arm'], r['policy'], r['id']): r for r in mappings}
    baseline = rows(args.primary_report / 'baseline-rows.jsonl')
    args.output.mkdir(parents=True, exist_ok=False)
    result = {}
    for arm in ('17m', '32m', '68m'):
        path = args.shadows / (arm + '-selections.jsonl')
        if sha(path) != shadow['models'][arm]['selections_sha256']:
            raise ValueError('shadow selections changed')
        selections = rows(path)
        for policy in ('neural', 'preserve_ken'):
            output = []
            for selection in (r for r in selections if r['policy'] == policy):
                qid = selection['id']
                case, accepted = cases[qid], gold[qid]['acceptable_units']
                available = pools[qid]['cards']
                index = selection['top_index']
                card = available[index] if index is not None else None
                link = mapping[(arm, policy, qid)]
                judge = judgments[link['judge_id']]
                identity = identity_hit(card, accepted)
                visible = blind_pass(card, case['facets'], judge)
                retained = any(identity_hit(available[i], accepted) for i in selection['kept'])
                recall10 = any(identity_hit(c, accepted) for c in available[:10])
                output.append({'id': qid, 'repo_id': case['repo_id'], 'target_kind': case['target_kind'],
                    'language': case['language'], 'query_style': case['query_style'],
                    'recall10': recall10, 'recall20': any(identity_hit(c, accepted) for c in available),
                    'retained_recall10': retained, 'correct_coverage_lost': recall10 and not retained,
                    'identity': identity, 'blind_verifiable': visible,
                    'joint': identity and visible and link['source_valid'],
                    'abstain': bool(selection['all_rejected'] or judge.get('abstain', False)),
                    'judge_id': link['judge_id']})
            if len(output) != 200 or len({r['id'] for r in output}) != 200:
                raise ValueError('cannot reduce the original denominator')
            name = arm + '-' + policy
            report = {'overall': summarize(output),
                'retained_recall10': sum(r['retained_recall10'] for r in output) / 200,
                'correct_coverage_lost': sum(r['correct_coverage_lost'] for r in output),
                'versus_baseline': {k: cluster_difference(output, baseline, key=k) for k in ('identity', 'joint')},
                'target_kind': {kind: summarize([r for r in output if r['target_kind'] == kind])
                    for kind in ('class', 'module', 'symbol', 'file')},
                'unlisted_alternatives_for_source_audit': [r['id'] for r in output
                    if r['blind_verifiable'] and not r['identity']]}
            report['goals_met'] = bool(primary['arms']['baseline']['calibration_gate_passed']
                and report['overall']['recall10']['rate'] >= .95
                and report['retained_recall10'] >= .95 and report['overall']['joint']['rate'] >= .9)
            result[name] = report
            (args.output / (name + '-rows.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in output))
    (args.output / 'report.json').write_text(json.dumps({'scope': 'offline fixed-score shadows, not live latency',
        'queries': 200, 'arms': result, 'calibration_rejection': shadow['models'],
        'inputs': {'primary_report': sha(args.primary_report / 'report.json'),
                   'final_judgment_seal': sha(args.final_judgment_seal),
                   'shadows_registration': sha(args.shadows / 'registration.json')}}, indent=2))


if __name__ == '__main__':
    main()
