import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ettin_cpu import sha
from verifiable_pieces import canonical
from verifiable_judgment_seal import close_judgments
from verifiable_judgment_seal import validate_opinions


class BlindClosure(unittest.TestCase):
    def fixture(self, root, *, quote='return value', omit=False):
        inputs = root / 'inputs'
        inputs.mkdir()
        row = {'judge_id': 'J-synthetic', 'target_kind': 'symbol', 'facets': [{'id': 'f1'}],
               'card': {'unit': {'path': 'synthetic.py'}, 'excerpts': [{'content': 'return value'}]}}
        p = inputs / 'class-symbol.jsonl'
        p.write_text(canonical(row) + '\n')
        (inputs / 'receipt.json').write_text(json.dumps({'files': {p.name: sha(p)}}))
        judgments = root / 'judgments.jsonl'
        opinion = {'judge_id': row['judge_id'], 'relevance': 2, 'sufficiency': 2, 'abstain': False,
                   'requirements': [{'facet_id': 'f1', 'state': 'supported',
                                     'evidence': [{'excerpt': 0, 'quote': quote}]}]}
        judgments.write_text('' if omit else canonical(opinion) + '\n')
        gate = root / 'gate.json'
        gate.write_text(json.dumps({'calibration_gate_passed': True}))
        return inputs, [judgments], gate

    def test_closure_binds_exact_inputs_opinions_and_gate_without_quality_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs, opinions, gate = self.fixture(root)
            seal = close_judgments(inputs, opinions, gate)
            self.assertEqual(seal['status'], 'ALL principal blind judgments closed before Gold')
            self.assertEqual(seal['blind_input_receipt_sha256'], sha(inputs / 'receipt.json'))
            self.assertEqual(seal['judgment_files'], {str(opinions[0]): sha(opinions[0])})
            self.assertEqual(seal['calibration_gate_sha256'], sha(gate))
            self.assertEqual(seal['counts'], {'class-symbol': 1, 'module-file': 0})

    def test_missing_opinion_cannot_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'scope'):
                close_judgments(*self.fixture(Path(tmp), omit=True))

    def test_nonliteral_citation_cannot_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'literal'):
                close_judgments(*self.fixture(Path(tmp), quote='invented source'))

    def test_duplicate_opinion_cannot_close_even_when_values_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs, opinions, gate = self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                close_judgments(inputs, opinions * 2, gate)

    def test_facets_may_be_permuted_but_must_each_be_present_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs, opinions, gate = self.fixture(Path(tmp))
            visible = inputs / 'class-symbol.jsonl'
            row = json.loads(visible.read_text())
            row['facets'].append({'id': 'f2'})
            visible.write_text(canonical(row) + '\n')
            receipt = inputs / 'receipt.json'
            receipt.write_text(json.dumps({'files': {visible.name: sha(visible)}}))
            judgment = json.loads(opinions[0].read_text())
            judgment['requirements'].insert(0, {**judgment['requirements'][0], 'facet_id': 'f2'})
            opinions[0].write_text(canonical(judgment) + '\n')
            close_judgments(inputs, opinions, gate)
            judgment['requirements'][1]['facet_id'] = 'f2'
            opinions[0].write_text(canonical(judgment) + '\n')
            with self.assertRaisesRegex(ValueError, 'facet scope'):
                close_judgments(inputs, opinions, gate)

    def test_seal_hashes_the_validated_snapshot_even_if_files_change_before_sealing(self):
        with tempfile.TemporaryDirectory() as tmp:
            inputs, opinions, gate = self.fixture(Path(tmp))
            receipt = inputs / 'receipt.json'
            original = {p: sha(p) for p in [*opinions, gate, receipt]}

            def validate_then_change(*args):
                result = validate_opinions(*args)
                for path in original:
                    path.write_text('changed after validation')
                return result

            with patch('verifiable_judgment_seal.validate_opinions', side_effect=validate_then_change):
                seal = close_judgments(inputs, opinions, gate)
            self.assertEqual(seal['judgment_files'][str(opinions[0])], original[opinions[0]])
            self.assertEqual(seal['calibration_gate_sha256'], original[gate])
            self.assertEqual(seal['blind_input_receipt_sha256'], original[receipt])


if __name__ == '__main__':
    unittest.main()
