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

    def test_official_span_overlap_can_pass_when_visible_fragment_misses(self):
        from benchmarks.data import Target, Task
        tasks = [Task('a', 'python', 'q', (Target('x', 140, 145),), (), 'semantic')]
        rows = {'semble-0000': {'results': [{'path': 'x',
            'entity_span': {'start_line': 1, 'end_line': 180},
            'evidence': [{'start_line': 100, 'end_line': 110}]}]}}
        self.assertEqual(evaluate_rows(tasks, rows)['macro_repo_ndcg10'], 1)
        self.assertEqual(evaluate_rows(tasks, rows, visible=True)['macro_repo_ndcg10'], 0)

    def test_two_targets_sharing_one_chunk_do_not_manufacture_two_rank_slots(self):
        from benchmarks.data import Target, Task
        tasks = [Task('a', 'python', 'q', (Target('x', 5, 10),),
                      (Target('x', 90, 95),), 'semantic')]
        rows = {'semble-0000': {'full_results': [{'chunk': {
            'file_path': 'x', 'start_line': 1, 'end_line': 100, 'content': 'source'}}]}}
        value = evaluate_rows(tasks, rows)
        self.assertEqual(value['per_query'][0]['relevant_ranks'], [1, 1])
        self.assertAlmostEqual(value['macro_repo_ndcg10'], 1/(1+1/math.log2(3)))

    def test_native_ranges_pass_through_exactly_even_for_zero_line_path_targets(self):
        from benchmarks.data import Target, Task
        from benchmarks.metrics import target_rank
        from types import SimpleNamespace
        task = Task('a', 'python', 'q', (Target('x'),), (), 'semantic')
        native = SimpleNamespace(chunk=SimpleNamespace(file_path='x', start_line=0, end_line=0))
        self.assertEqual(target_rank([native], task.relevant[0]), 1)
        rows = {'semble-0000': {'full_results': [{'chunk': {
            'file_path': 'x', 'start_line': 0, 'end_line': 0, 'content': ''}}]}}
        self.assertEqual(evaluate_rows([task], rows)['macro_repo_ndcg10'], 1)


if __name__ == '__main__':
    unittest.main()
