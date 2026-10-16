import json
from pathlib import Path
import tempfile
import unittest

from unseen_piece_score import evaluate_identity, load_closed


class IndependentIdentityScoring(unittest.TestCase):
    def setUp(self):
        self.cases = [{'id': 'a', 'repo_id': 'r1', 'target_kind': 'symbol', 'language': 'en'},
                      {'id': 'b', 'repo_id': 'r2', 'target_kind': 'file', 'language': 'es'}]
        self.gold = [
            {'id': 'a', 'acceptable_units': [{'target_kind': 'symbol', 'path': 'engine.py',
                'entity': {'kind': 'function', 'qualname': 'read', 'owner': None}}]},
            {'id': 'b', 'acceptable_units': [{'target_kind': 'file', 'path': 'settings.toml', 'entity': None}]}]

    def test_correct_file_with_wrong_function_is_a_failure(self):
        answers = [{'id': 'a', 'card': {'unit': {'target_kind': 'symbol', 'path': 'engine.py',
            'entity': {'kind': 'function', 'qualname': 'write', 'owner': None}}}, 'units': [
                {'target_kind': 'symbol', 'path': 'engine.py',
                 'entity': {'kind': 'function', 'qualname': 'read', 'owner': None}}]},
            {'id': 'b', 'card': {'unit': {'target_kind': 'file', 'path': 'settings.toml', 'entity': None}},
             'units': [{'target_kind': 'file', 'path': 'settings.toml', 'entity': None}]}]
        with self.assertRaisesRegex(ValueError, 'top1'):
            evaluate_identity(self.cases, answers, self.gold)
        answers[0]['units'].insert(0, answers[0]['card']['unit'])
        result, _ = evaluate_identity(self.cases, answers, self.gold)
        self.assertEqual(result['queries'], 2)
        self.assertEqual(result['top1']['count'], 1)
        self.assertEqual(result['recall10']['count'], 2)

    def test_empty_answer_is_counted_in_the_full_denominator(self):
        result, _ = evaluate_identity(self.cases, [{'id': 'a', 'card': None, 'units': []},
            {'id': 'b', 'card': None, 'units': []}], self.gold)
        self.assertEqual(result['queries'], 2)
        self.assertEqual(result['top1']['rate'], 0.)

    def test_valid_alternative_function_is_accepted(self):
        self.gold[0]['acceptable_units'].append({'target_kind': 'symbol', 'path': 'aliases.py',
            'entity': {'kind': 'function', 'qualname': 'load', 'owner': None}})
        unit = {'target_kind': 'symbol', 'path': 'aliases.py',
                'entity': {'kind': 'function', 'qualname': 'load', 'owner': None}}
        result, _ = evaluate_identity(self.cases, [{'id': 'a', 'card': {'unit': unit}, 'units': [unit]},
            {'id': 'b', 'card': None, 'units': []}], self.gold)
        self.assertEqual(result['top1']['count'], 1)
        self.assertEqual(result['recall10']['count'], 1)

    def test_duplicate_or_missing_queries_cannot_reduce_the_denominator(self):
        for answers in ([{'id': 'a', 'card': None, 'units': []}],
                        [{'id': 'a', 'card': None, 'units': []}] * 2):
            with self.subTest(answers=answers), self.assertRaises(ValueError):
                evaluate_identity(self.cases, answers, self.gold)

    def test_unclosed_run_is_rejected_before_any_reference_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'registration.json').write_text(json.dumps({'status': 'registered before public queries'}))
            with self.assertRaisesRegex(ValueError, 'closed'):
                load_closed(root)


if __name__ == '__main__':
    unittest.main()
