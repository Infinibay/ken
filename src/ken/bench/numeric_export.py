"""Convert an offline fitted numeric forest, refusing unsupported semantics."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ken.retrieval.numeric_ranker import NumericRanker


def export_numeric_ranker(dump: Mapping[str, Any], *, features: Sequence[str]) -> NumericRanker:
    if dump.get('num_class') != 1 or dump.get('average_output') is not False:
        raise ValueError('only additive single-score ranking forests are supported')
    if len(dump['feature_names']) != len(features):
        raise ValueError('exported feature schema does not match trained model')

    def convert(node: Mapping[str, Any]) -> dict[str, Any]:
        if 'leaf_value' in node:
            # LightGBM leaf values already include the learning rate.
            return {'value': node['leaf_value']}
        if node.get('decision_type') != '<=' or node.get('missing_type') not in ('None', 'NaN'):
            raise ValueError('unsupported ranking split semantics')
        return {'feature': node['split_feature'], 'threshold': node['threshold'],
                'left': convert(node['left_child']), 'right': convert(node['right_child'])}

    return NumericRanker.from_dict({'schema': 1, 'features': list(features),
        'trees': [convert(tree['tree_structure']) for tree in dump['tree_info']]})
