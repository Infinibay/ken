import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unseen_piece_score import evaluate_identity, load_closed
import unseen_piece_score as scorer


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


class PreGoldPublicGuards(unittest.TestCase):
    def exercise(self, defect, message):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [{'id': name, 'repo_id': 'r', 'target_kind': 'file'} for name in ('a', 'b')]
            public = root / 'public.jsonl'
            public.write_text(''.join(json.dumps(c) + '\n' for c in cases))
            variants = {'baseline': {'source_receipt': 'old'}, 'optimized': {'source_receipt': 'new'}}
            lock = {'variants': variants, 'queries': 2, 'public_cases': str(public),
                    'scorer_sha256': scorer.sha(scorer.__file__),
                    'grading_sha256': scorer.sha(scorer.verifiable_grading.__file__),
                    'input_pins': {str(public): scorer.sha(public)}, 'reference_pins': {}}
            if defect == 'scorer':
                lock['scorer_sha256'] = '0' * 64
            if defect == 'grading':
                lock['grading_sha256'] = '0' * 64
            locked = root / 'lock.json'; locked.write_text(json.dumps(lock))
            for variant in variants:
                capture = root / variant; repo = capture / 'r'; repo.mkdir(parents=True)
                chosen = cases[:1] if defect == 'incomplete' else cases
                answers = [c | {'card': None, 'units': [], 'native_units': [], 'pool_sha256': 'x'} for c in chosen]
                if defect == 'metadata':
                    answers[0]['target_kind'] = 'symbol'
                if defect in {'top1', 'duplicates', 'excess'}:
                    unit = {'target_kind': 'file', 'path': 'a.py', 'entity': None}
                    answers[0]['units'] = [unit]
                    if defect == 'top1':
                        answers[0]['card'] = {'unit': unit | {'path': 'wrong.py'}}
                    elif defect == 'duplicates':
                        answers[0]['units'] *= 2
                    else:
                        answers[0]['units'] = [unit | {'path': f'{i}.py'} for i in range(11)]
                (repo / 'answers.jsonl').write_text(''.join(json.dumps(a) + '\n' for a in answers))
                times = [{'id': c['id'], 'ms': 1., 'cpu_ms': 1.} for c in chosen]
                if defect == 'timings':
                    times[-1]['id'] = times[0]['id']
                performance = {'providers': ['CPUExecutionProvider'], 'heavy_imports': [],
                    'timings': times, 'peak_rss_native': 100, 'rss_unit': 'bytes'}
                (repo / 'performance.json').write_text(json.dumps(performance))
                role = 'baseline' if defect == 'role' else variant
                registration = {'status': 'ALL additional public outputs closed without Gold',
                    'lock_sha256': scorer.sha(locked), 'variant': role, 'variant_policy': variants[variant],
                    'closed': {'r': {name: scorer.sha(repo / name) for name in ('answers.jsonl', 'performance.json')}}}
                (capture / 'registration.json').write_text(json.dumps(registration))
            candidate = root / ('baseline' if defect == 'same_path' else 'optimized')
            argv = ['score', '--baseline', str(root / 'baseline'), '--candidate', str(candidate),
                '--lock', str(locked), '--output', str(root / 'out'), '--private-output', str(root / 'private'),
                '--gold', str(root / 'GOLD-MUST-NOT-BE-OPENED-1'), str(root / 'GOLD-MUST-NOT-BE-OPENED-2')]
            # Reference files deliberately do not exist: passing the public guard
            # and trying to read them would raise a different failure.
            with patch('sys.argv', argv), self.assertRaisesRegex(ValueError, message):
                scorer.main()
            self.assertFalse((root / 'private').exists())

    def test_equally_incomplete_runs_are_rejected_before_gold(self):
        self.exercise('incomplete', 'full public query set')

    def test_scorer_pin_is_checked_before_gold(self):
        self.exercise('scorer', 'scorer changed')

    def test_grading_dependency_pin_is_checked_before_gold(self):
        self.exercise('grading', 'grading dependency changed')

    def test_same_capture_cannot_be_used_as_both_arms(self):
        self.exercise('same_path', 'distinct')

    def test_registration_must_match_its_predeclared_role(self):
        self.exercise('role', 'variant')

    def test_answer_metadata_must_match_the_public_request(self):
        self.exercise('metadata', 'request metadata')

    def test_timing_ids_cannot_duplicate_or_replace_queries(self):
        self.exercise('timings', 'timing')

    def test_top1_card_mismatch_is_rejected_before_gold(self):
        self.exercise('top1', 'top1')

    def test_duplicate_units_are_rejected_before_gold(self):
        self.exercise('duplicates', 'top10')

    def test_excess_units_are_rejected_before_gold(self):
        self.exercise('excess', 'top10')


if __name__ == '__main__':
    unittest.main()
