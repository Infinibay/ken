"""Normalize curator variant names; never alter labels, evidence or thresholds."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

VARIANTS = {'sufficient': 'sufficient', 'sparse': 'identity_only_insufficient',
            'identity_only_insufficient': 'identity_only_insufficient',
            'distractor': 'faithful_plausible_distractor',
            'faithful_plausible_distractor': 'faithful_plausible_distractor'}


def normalize_row(row):
    if row['variant'] not in VARIANTS:
        raise ValueError('unknown calibration variant')
    return {**row, 'variant': VARIANTS[row['variant']]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--labels', type=Path, nargs='+', required=True)
    parser.add_argument('--input-sha256', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if len(args.labels) != len(args.input_sha256):
        raise ValueError('every original label file requires its previously sealed SHA')
    output, pins = [], {}
    for path, expected in zip(args.labels, args.input_sha256, strict=True):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError('original calibration labels changed')
        pins[str(path)] = digest
        output.extend(normalize_row(json.loads(line)) for line in data.splitlines())
    counts = Counter(r['variant'] for r in output)
    if len({r['card_id'] for r in output}) != 60 or counts != dict.fromkeys(
            ('sufficient', 'identity_only_insufficient', 'faithful_plausible_distractor'), 20):
        raise ValueError('all60 original cards and20 of each semantic variant required')
    args.output.mkdir(parents=True, exist_ok=False)
    data = ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'
                   for r in output).encode()
    (args.output / 'labels.jsonl').write_bytes(data)
    receipt = {'scope': 'calibration semantic variant vocabulary only; original scores/labels/evidence unchanged',
        'original_labels': pins, 'mapping': VARIANTS, 'counts': dict(counts),
        'labels_sha256': hashlib.sha256(data).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps({'counts': dict(counts), 'labels_sha256': receipt['labels_sha256']}))


if __name__ == '__main__':
    main()
