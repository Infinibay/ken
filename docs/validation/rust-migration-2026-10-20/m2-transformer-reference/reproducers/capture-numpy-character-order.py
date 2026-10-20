"""Pure sorting oracle; no model/tensor runtime is loaded."""
import json
import platform
import sys
import numpy as np

assert np.__version__ == '2.4.4'
cases = []
for count in (0, 1, 2, 15, 16, 17, 31, 33, 64, 257, 1024):
    for pattern in ('equal', 'increasing', 'decreasing', 'mixed'):
        lengths = [8] * count
        if pattern == 'increasing':
            lengths = list(range(count))
        elif pattern == 'decreasing':
            lengths = list(range(count, 0, -1))
        elif pattern == 'mixed':
            lengths = [((index * 1103515245 + 12345) >> 16) % 23 for index in range(count)]
        keys = [-length for length in lengths]
        order = np.argsort(keys)
        inverse = np.argsort(order)
        assert order.dtype == np.dtype('int64')
        assert sorted(order.tolist()) == list(range(count))
        assert order[inverse].tolist() == list(range(count))
        cases.append({'id': f'{pattern}-{count}', 'unicode_character_lengths': lengths,
                      'order': order.tolist(), 'inverse': inverse.tolist()})
json.dump({'format': 'ken-original-st-character-order/1', 'numpy': np.__version__,
           'os': platform.system(), 'arch': platform.machine(), 'cases': cases,
           'scope': 'Exact default np.argsort(-Unicode-character-length) and inverse order, no model inference.'},
          sys.stdout, separators=(',', ':'))
print()
