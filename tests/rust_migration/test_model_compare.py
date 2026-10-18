"""Negative controls reject plausible but incorrect native model reports."""
from copy import deepcopy
import math

from tools.rust_migration.model_compare import compare_output


def pair():
    expected = {'dimension': 3, 'assets_fingerprint': 'asset', 'identity': {'model_id': 'test/static'},
        'cases': [{'id': 'sample', 'calls': [{'op': 'tokens'}, {'op': 'query'}, {'op': 'passages'}]}],
        'results': [{'id': 'sample', 'calls': [[3, 4], [.6, .8, 0.0],
            {'vectors': [[.6, .8, 0.0], [0.0, 0.0, 0.0]], 'rows': [0, 1]}]}]}
    actual = {'dimension': 3, 'assets_fingerprint': 'asset', 'compatible_identity': {'model_id': 'test/static'},
        'runtime': {'engine': 'rust', 'ken_models': '0.18.0', 'tokenizers': '0.22.2',
                    'safetensors': '0.8.0', 'half': '2.7.1', 'device': 'cpu'},
        'results': [{'id': 'sample', 'calls': [[3, 4], [.6, .8, 0.0], [[.6, .8, 0.0], [0.0, 0.0, 0.0]]]}]}
    return expected, actual


def test_empty_or_mutated_probe_cannot_pass():
    expected, valid = pair()
    assert compare_output(expected, valid) == []
    for invalid in [{}, {**valid, 'results': []}, {**valid, 'assets_fingerprint': 'wrong'},
                    {**valid, 'dimension': 256}, {**valid, 'compatible_identity': {}},
                    {**valid, 'runtime': {**valid['runtime'], 'engine': 'python'}}]:
        assert compare_output(expected, invalid)
    zero = deepcopy(valid); zero['results'][0]['calls'][1] = [0.0, 0.0, 0.0]
    assert compare_output(expected, zero)
    extra = deepcopy(valid); extra['results'].append(extra['results'][0])
    assert compare_output(expected, extra)


def test_wrong_token_order_and_nonfinite_vectors_fail():
    expected, valid = pair()
    for mutated in [[4, 3], [3, 4, 5], [True, 4], [3.0, 4]]:
        wrong = deepcopy(valid); wrong['results'][0]['calls'][0] = mutated
        assert compare_output(expected, wrong)
    for number in [math.nan, math.inf, -math.inf, True]:
        wrong = deepcopy(valid); wrong['results'][0]['calls'][1][0] = number
        assert compare_output(expected, wrong)
    wrong = deepcopy(valid); wrong['results'][0]['calls'][2][1][0] = 1e-10
    assert compare_output(expected, wrong), 'expected zero vector must stay exactly zero'
    wrong = deepcopy(valid); wrong['results'][0]['calls'][2].reverse()
    assert compare_output(expected, wrong), 'row order cannot be normalized'
