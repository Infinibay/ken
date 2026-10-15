"""Close a complete blind opinion scope after mechanical citation validation.

No relevance decision is inferred, no Gold is read, and no quality total is
printed. Opinions remain exactly as written by their independent reviewers.
"""
import argparse
import hashlib
import json
from pathlib import Path


def snapshot(path):
    data = Path(path).read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def visible_snapshot(directory):
    data, receipt_sha = snapshot(directory / 'receipt.json')
    receipt = json.loads(data)
    inputs = {}
    for name, expected in receipt['files'].items():
        data, actual = snapshot(directory / name)
        if actual != expected:
            raise ValueError('blind input changed')
        if name != 'mapping.jsonl':
            for row in map(json.loads, data.splitlines()):
                if row['judge_id'] in inputs:
                    raise ValueError('duplicate visible input')
                inputs[row['judge_id']] = row
    return inputs, receipt_sha


def validate_opinions(inputs, judgment_files):
    judgments = {}
    pins = {}
    for path in judgment_files:
        data, digest = snapshot(path)
        pins[str(path)] = digest
        for opinion in map(json.loads, data.splitlines()):
            jid = opinion['judge_id']
            if jid in judgments:
                raise ValueError('duplicate opinion')
            judgments[jid] = opinion
    if set(inputs) != set(judgments):
        raise ValueError('visible input and opinion scope differ')
    counts = {'class-symbol': 0, 'module-file': 0}
    for jid, visible in inputs.items():
        opinion = judgments[jid]
        kind = visible['target_kind']
        if kind not in {'class', 'symbol', 'module', 'file'}:
            raise ValueError('unknown requested unit')
        counts['class-symbol' if kind in {'class', 'symbol'} else 'module-file'] += 1
        for field in ('relevance', 'sufficiency'):
            if type(opinion[field]) is not int or opinion[field] not in (0, 1, 2):
                raise ValueError('invalid ordinal judgment')
        if type(opinion['abstain']) is not bool:
            raise ValueError('invalid abstention')
        observed = [r['facet_id'] for r in opinion['requirements']]
        expected = [f['id'] for f in visible['facets']]
        if (len(observed) != len(set(observed)) or len(expected) != len(set(expected))
                or set(observed) != set(expected)):
            raise ValueError('public facet scope differs')
        for requirement in opinion['requirements']:
            state, evidence = requirement['state'], requirement['evidence']
            if state not in {'supported', 'contradicted', 'unobservable'}:
                raise ValueError('invalid observation state')
            if state == 'unobservable':
                if evidence != [] or not requirement.get('reason'):
                    raise ValueError('unobservable requires reason and no evidence')
            elif not evidence:
                raise ValueError('observed facet requires evidence')
            for citation in evidence:
                card = visible['card']
                quote, index = citation['quote'], citation['excerpt']
                if card is None or not quote.strip():
                    raise ValueError('missing literal evidence')
                if index == 'unit':
                    text = json.dumps(card['unit'], ensure_ascii=False, sort_keys=True)
                else:
                    if type(index) is not int or not 0 <= index < len(card['excerpts']):
                        raise ValueError('invalid excerpt reference')
                    text = card['excerpts'][index]['content']
                if quote not in text:
                    raise ValueError('nonliteral citation')
    return counts, pins


def close_judgments(blind_inputs, judgment_files, calibration_gate):
    data, gate_sha = snapshot(calibration_gate)
    gate = json.loads(data)
    if gate.get('calibration_gate_passed') is not True:
        raise ValueError('calibration gate has not passed')
    inputs, receipt_sha = visible_snapshot(blind_inputs)
    counts, opinion_pins = validate_opinions(inputs, judgment_files)
    return {'status': 'ALL principal blind judgments closed before Gold',
        'blind_input_receipt_sha256': receipt_sha,
        'judgment_files': opinion_pins,
        'calibration_gate_passed': True, 'calibration_gate_sha256': gate_sha,
        'counts': counts, 'script_sha256': snapshot(__file__)[1],
        'scope': 'all visible IDs/facets and literal citations validated; no Gold or quality grading'}


def main():
    parser = argparse.ArgumentParser()
    for name in ('blind-inputs', 'calibration-gate', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--judgments', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    seal = close_judgments(args.blind_inputs, args.judgments, args.calibration_gate)
    with args.output.open('x') as handle:
        handle.write(json.dumps(seal, indent=2))
    print(json.dumps({'counts': seal['counts'], 'seal_sha256': snapshot(args.output)[1]}))


if __name__ == '__main__':
    main()
