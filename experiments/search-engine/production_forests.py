"""Build generic additive forests without repository-dependent runtime selection."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from ken.retrieval.numeric_ranker import NumericRanker


def mean_forests(models: Sequence[NumericRanker]) -> NumericRanker:
    """Equal model weight, regardless of the number of trees in each model."""
    if not models:
        raise ValueError('a nonempty model collection is required')
    features = models[0].features
    if any(m.features != features for m in models):
        raise ValueError('all models require the same named feature schema')
    def scale(tree):
        if 'value' in tree:
            return {'value': tree['value'] / len(models)}
        return {'feature': tree['feature'], 'threshold': tree['threshold'],
                'left': scale(tree['left']), 'right': scale(tree['right'])}
    return NumericRanker.from_dict({'schema': 1, 'features': features,
        'trees': [scale(t) for model in models for t in model.to_dict()['trees']]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('new output directory required; preserve prior models')
    paths = sorted(args.model)
    if len(set(p.resolve() for p in paths)) != len(paths):
        raise ValueError('duplicate input models are not independent votes')
    snapshots = [p.read_bytes() for p in paths]
    models = [NumericRanker.from_dict(json.loads(data)) for data in snapshots]
    merged = mean_forests(models)
    args.output.mkdir(parents=True)
    payload = json.dumps(merged.to_dict(), sort_keys=True, separators=(',', ':')) + '\n'
    (args.output / 'model.json').write_text(payload)
    record = {'policy': 'equal-model-score-mean-v1', 'models': len(models),
        'source_inputs': [{'path': str(p.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
                          'model_fingerprint': m.fingerprint} for p,m,data in zip(paths,models,snapshots,strict=True)],
        'model_fingerprint': merged.fingerprint, 'model_sha256': hashlib.sha256(payload.encode()).hexdigest(),
        'feature_count': len(merged.features), 'trees': len(merged.to_dict()['trees']),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Generic model artifact; no case, query, repository identity or private labels enter inference. Original development only; not independent acceptance.'}
    (args.output / 'receipt.json').write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main()
