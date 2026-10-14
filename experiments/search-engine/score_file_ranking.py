"""Auxiliary binary file NDCG@10; never the strict acceptance metric."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def file_ndcg(paths, relevant, k=10):
    # Credit each relevant file only at its first returned position.
    seen = set(); gain = 0.0
    for rank, path in enumerate(paths[:k], 1):
        if path in relevant and path not in seen:
            gain += 1 / math.log2(rank + 1)
        seen.add(path)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return gain / ideal if ideal else 0.0


def main():
    assert file_ndcg(['a'], {'a'}) == 1
    assert file_ndcg(['x', 'a'], {'a'}) == 1/math.log2(3)
    assert file_ndcg(['a', 'a'], {'a'}) == 1
    assert file_ndcg(['a', 'b'], {'a', 'b'}) == 1
    assert file_ndcg([], {'a'}) == 0
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--ken', type=Path, required=True)
    parser.add_argument('--semble', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = [json.loads(l) for l in args.dataset.read_text().splitlines()]
    result = {'metric': 'binary unique-file NDCG@10, first occurrence per relevant file',
        'scope': 'auxiliary diagnostic on original400development; not Semble1251benchmark or strict acceptance',
        'dataset_sha256': hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'runs': {}}
    for tool, path in [('ken', args.ken), ('semble', args.semble)]:
        rows = [json.loads(l) for l in path.read_text().splitlines()]
        by_id = {r['id']: r for r in rows}
        if len(rows) != len(by_id) or set(by_id) != {c['id'] for c in cases}:
            raise ValueError('exact complete response set required')
        scores = []
        for case in cases:
            relevant = {a['path'] for a in case['alternatives']}
            paths = [r['path'] for r in by_id[case['id']].get('results', [])][:10]
            scores.append({'id': case['id'], 'ndcg10': file_ndcg(paths, relevant),
                'file_top1': bool(paths and paths[0] in relevant),
                'file_hit10': any(p in relevant for p in paths)})
        result['runs'][tool] = {'responses_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'count': len(scores), 'file_ndcg10': sum(r['ndcg10'] for r in scores)/len(scores),
            'file_top1': sum(r['file_top1'] for r in scores)/len(scores),
            'file_hit10': sum(r['file_hit10'] for r in scores)/len(scores), 'rows': scores}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k:{n:v for n,v in values.items() if n!='rows'} for k,values in result['runs'].items()}))


if __name__ == '__main__':
    main()
