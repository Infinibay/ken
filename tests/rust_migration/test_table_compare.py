"""The table gate must reject convincing but wrong process results."""
from copy import deepcopy
import math

from tools.rust_migration.table_compare import RUNTIME, compare_output


def test_table_comparison_rejects_wrong_tokens_vectors_shapes_and_runtime():
    expected = {'dimension': 3, 'artifact': {'sha256': 'a'*64, 'bytes': 10}, 'meta': {},
        'cases': [{'id': 'one', 'calls': [{'op': 'tokens'}, {'op': 'count'},
                                         {'op': 'query'}, {'op': 'queries'}]}],
        'results': [{'id': 'one', 'calls': [[0, 4, 1], 3, [.6, .8, 0], [[0, 0, 0]]]}]}
    valid = {'dimension': 3, 'artifact': expected['artifact'], 'meta': {}, 'runtime': RUNTIME,
        'results': [{'id': 'one', 'calls': [[0, 4, 1], 3, [.6, .8, 0], [[0, 0, 0]]],
                     'load_ns': 1, 'inference_ns': 1,
                     'peak_after_load_bytes': 1, 'peak_after_inference_bytes': 1}]}
    assert compare_output(expected, valid) == []
    for key, value in [('dimension', 4), ('artifact', {}), ('results', []),
                        ('meta', {'different': True}), ('runtime', {'engine': 'python'})]:
        assert compare_output(expected, valid | {key: value})
    for index, value in [(0, [0, 1]), (0, [0, True, 1]), (0, [0, 4.0, 1]),
                         (1, True), (2, [.61, .8, 0]), (2, [0, 0, 0]),
                         (2, [math.nan, .8, 0]), (2, [math.inf, .8, 0]),
                         (3, [[1e-12, 0, 0]]), (3, [])]:
        bad = deepcopy(valid)
        bad['results'][0]['calls'][index] = value
        assert compare_output(expected, bad)
    bad = deepcopy(valid); bad['results'][0]['id'] = 'other'
    assert compare_output(expected, bad)
    assert compare_output(expected, [])
    bad = deepcopy(valid); bad['results'][0]['peak_after_inference_bytes'] = 0
    assert compare_output(expected, bad)
