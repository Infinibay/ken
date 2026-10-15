import unittest
from ettin_stability_probe import aligned_scores


class PairIdentity(unittest.TestCase):
    def test_batch_reordering_and_single_pair_calls_keep_original_pair_identity(self):
        class Model:
            def score(self, query, texts):
                return [float(len(t)) for t in texts], {'pad_id': 50283}
        texts = ['a', 'bb', 'ccc']
        for single in (False, True):
            scores, _ = aligned_scores(Model(), 'synthetic query', texts, [2, 0, 1], single)
            self.assertEqual(scores, [1, 2, 3])

    def test_invalid_permutation_is_rejected_before_inference(self):
        with self.assertRaisesRegex(ValueError, 'permutation'):
            aligned_scores(None, 'synthetic query', ['a', 'bb'], [0, 0], False)


if __name__ == '__main__':
    unittest.main()
