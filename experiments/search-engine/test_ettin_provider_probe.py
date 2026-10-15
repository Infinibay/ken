import copy
import unittest

from ettin_provider_probe import provider_choice


class ProviderEligibility(unittest.TestCase):
    def setUp(self):
        self.cpu = {'ok': True, 'profiles': {'short': {'p50_ms': 100, 'scores': list(range(10))}}}
        self.acc = copy.deepcopy(self.cpu)
        self.acc['accelerator_nodes'] = 3
        self.acc['profiles']['short']['p50_ms'] = 50

    def test_faster_valid_accelerator_wins(self):
        self.assertEqual(provider_choice(self.cpu, self.acc, 'short'), 'CoreMLExecutionProvider')

    def test_unavailable_or_unused_or_slower_accelerator_keeps_cpu(self):
        self.assertEqual(provider_choice(self.cpu, {'ok': False}, 'short'), 'CPUExecutionProvider')
        self.acc['accelerator_nodes'] = 0
        self.assertEqual(provider_choice(self.cpu, self.acc, 'short'), 'CPUExecutionProvider')
        self.acc['accelerator_nodes'] = 3
        self.acc['profiles']['short']['p50_ms'] = 110
        self.assertEqual(provider_choice(self.cpu, self.acc, 'short'), 'CPUExecutionProvider')

    def test_changed_scores_or_rank_are_ineligible(self):
        self.acc['profiles']['short']['scores'][1] = 12
        self.assertEqual(provider_choice(self.cpu, self.acc, 'short'), 'CPUExecutionProvider')

    def test_cpu_is_required(self):
        with self.assertRaises(ValueError):
            provider_choice({'ok': False}, self.acc, 'short')


if __name__ == '__main__':
    unittest.main()
