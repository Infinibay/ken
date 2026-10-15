import unittest
from unittest.mock import patch

from ettin_cpu import CPUReranker
from ettin_fixed_provider_probe import FixedInputReranker


class FixedBatchOutput(unittest.TestCase):
    def test_duplicate_padding_cannot_become_an_answer(self):
        model = object.__new__(FixedInputReranker)
        timing = {'token_ms': 1, 'inference_ms': 2, 'pair_tokens': [512] * 4}
        calls = [([1, 2, 3, 4], timing), ([5, 6, 7, 8], timing), ([9, 10, 901, 902], timing)]
        with patch.object(CPUReranker, 'score', side_effect=calls) as score:
            values, details = model.score('query', [str(i) for i in range(10)])
        self.assertEqual(values, list(range(1, 11)))
        self.assertEqual(score.call_args.args, ('query', ['8', '9', '9', '9']))
        self.assertEqual(details['pair_tokens'], [512] * 10)
        self.assertEqual(details['token_ms'], 3)

    def test_empty_candidates_do_not_invoke_inference(self):
        model = object.__new__(FixedInputReranker)
        with patch.object(CPUReranker, 'score') as score:
            values, _ = model.score('query', [])
        self.assertEqual(values, [])
        score.assert_not_called()


if __name__ == '__main__':
    unittest.main()
