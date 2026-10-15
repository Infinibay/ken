"""Reuse sealed opinions only for canonical-byte-identical visible query/cards."""
import argparse
import json
from pathlib import Path

from ettin_cpu import sha
from verifiable_pieces import canonical


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def visible_inputs(directory):
    receipt = json.loads((directory / 'receipt.json').read_text())
    inputs = {}
    for name, expected in receipt['files'].items():
        if sha(directory / name) != expected:
            raise ValueError('blind input changed')
        if name != 'mapping.jsonl':
            for row in rows(directory / name):
                if row['judge_id'] in inputs:
                    raise ValueError('duplicate visible input')
                inputs[row['judge_id']] = row
    return receipt, inputs


def main():
    parser = argparse.ArgumentParser()
    for name in ('prior-inputs', 'prior-judgment-seal', 'current-inputs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    prior_receipt, prior = visible_inputs(args.prior_inputs)
    current_receipt, current = visible_inputs(args.current_inputs)
    seal = json.loads(args.prior_judgment_seal.read_text())
    if (seal.get('status') != 'ALL principal blind judgments closed before Gold'
            or seal.get('calibration_gate_passed') is not True
            or seal['blind_input_receipt_sha256'] != sha(args.prior_inputs / 'receipt.json')
            or prior_receipt['public_cases_sha256'] != current_receipt['public_cases_sha256']):
        raise ValueError('prior opinion closure or query scope differs')
    judgments = {}
    for path, expected in seal['judgment_files'].items():
        if sha(path) != expected:
            raise ValueError('prior judgment changed')
        for row in rows(path):
            if row['judge_id'] in judgments:
                raise ValueError('duplicate prior judgment')
            judgments[row['judge_id']] = row
    if set(judgments) != set(prior):
        raise ValueError('prior judgments incomplete')
    reused, new = {}, []
    for jid, value in current.items():
        if jid in prior:
            if canonical(value).encode() != canonical(prior[jid]).encode():
                raise ValueError('cannot reuse a changed visible input')
            reused[jid] = judgments[jid]
        else:
            new.append(value)
    args.output.mkdir(parents=True, exist_ok=False)
    counts = {}
    for role, kinds in [('class-symbol', {'class', 'symbol'}), ('module-file', {'module', 'file'})]:
        extra = [r for r in new if r['target_kind'] in kinds]
        known = [j for jid, j in reused.items() if current[jid]['target_kind'] in kinds]
        (args.output / ('new-' + role + '.jsonl')).write_text(''.join(canonical(r) + '\n' for r in extra))
        (args.output / ('reused-' + role + '-judgments.jsonl')).write_text(''.join(canonical(r) + '\n' for r in known))
        counts[role] = {'new': len(extra), 'reused': len(known)}
    receipt = {'scope': 'source-authenticated current inputs; reuse only identical visible bytes; no Gold',
        'prior_input_receipt_sha256': sha(args.prior_inputs / 'receipt.json'),
        'prior_judgment_seal_sha256': sha(args.prior_judgment_seal),
        'current_input_receipt_sha256': sha(args.current_inputs / 'receipt.json'),
        'counts': counts, 'script_sha256': sha(__file__),
        'files': {p.name: sha(p) for p in args.output.glob('*.jsonl')}}
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(counts))


if __name__ == '__main__':
    main()
