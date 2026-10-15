"""Adapter invariants, using Semble's unchanged public scorer."""
import math
import unittest

from semble_public_score import evaluate_rows, locations


class OfficialAdapterTests(unittest.TestCase):
    def test_native_entity_and_visible_fragment_have_separate_ranges(self):
        response = {"results": [{"path": "src/x.py", "entity_span": {
            "start_line": 5, "end_line": 180}, "evidence": [
                {"start_line": 100, "end_line": 110},
                {"start_line": 150, "end_line": 155}]}]}
        native = locations(response, visible=False)
        visible = locations(response, visible=True)
        self.assertEqual((native[0].chunk.start_line, native[0].chunk.end_line), (5, 180))
        self.assertEqual((visible[0].chunk.start_line, visible[0].chunk.end_line), (100, 110))
        self.assertEqual(len(visible), 1)  # No flattening fragments into extra ranks.

    def test_duplicate_results_keep_original_ranks_and_official_binary_gain(self):
        from benchmarks.data import Target, Task
        tasks = [Task('a', 'python', 'q', (Target('x'), Target('y')), (), 'semantic')]
        rows = {'semble-0000': {'results': [
            {'path': p, 'entity_span': {'start_line': 1, 'end_line': 2}}
            for p in ('x', 'x', 'y')]}}
        result = evaluate_rows(tasks, rows)
        self.assertAlmostEqual(result['macro_repo_ndcg10'], 1.5 / (1 + 1/math.log2(3)))

    def test_missing_query_is_zero_and_macro_repo_is_not_query_weighted(self):
        from benchmarks.data import Target, Task
        tasks = [Task(repo, 'python', str(i), (Target('x'),), (), 'semantic')
                 for i, repo in enumerate(('a', 'a', 'b'))]
        hit = {'results': [{'path': 'x', 'entity_span': {'start_line': 1, 'end_line': 1}}]}
        result = evaluate_rows(tasks, {'semble-0000': hit, 'semble-0001': hit})
        self.assertEqual(result['queries'], 3)
        self.assertEqual(result['missing'], 1)
        self.assertEqual(result['macro_repo_ndcg10'], .5)
        self.assertAlmostEqual(result['micro_query_ndcg10'], 2/3)


if __name__ == '__main__':
    unittest.main()
