import unittest

from verifiable_shadow import select_order


class RejectionAndOrdering(unittest.TestCase):
    def test_same_rejection_has_two_independent_ordering_policies(self):
        scores = [-4.0, 1.0, 5.0, 2.0]
        self.assertEqual(select_order(scores, 1.0, 'preserve_ken'), [1, 2, 3])
        self.assertEqual(select_order(scores, 1.0, 'neural'), [2, 3, 1])

    def test_cutoff_ties_empty_and_nonfinite_are_explicit(self):
        self.assertEqual(select_order([1.0, 1.0], 1.0, 'neural'), [0, 1])
        self.assertEqual(select_order([1.0], 2.0, 'preserve_ken'), [])
        self.assertEqual(select_order([], 2.0, 'neural'), [])
        with self.assertRaises(ValueError):
            select_order([float('nan')], 0, 'neural')
        with self.assertRaises(ValueError):
            select_order([1], float('inf'), 'preserve_ken')
        with self.assertRaises(ValueError):
            select_order([1], 0, 'unknown')


if __name__ == '__main__':
    unittest.main()
