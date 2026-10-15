import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ettin_cpu import sha
from verifiable_blind_reuse import main
from verifiable_pieces import canonical


class SealedOpinionReuse(unittest.TestCase):
    def fixture(self, root, *, changed=False, gate=True):
        prior = root / 'prior'
        current = root / 'current'
        row = {'judge_id': 'J-same', 'query': 'synthetic query',
               'target_kind': 'symbol', 'language': 'en', 'facets': [], 'card': None}
        new = {**row, 'judge_id': 'J-new', 'target_kind': 'file'}
        for directory, values in ((prior, [row]), (current, [{**row, 'query': 'changed'} if changed else row, new])):
            directory.mkdir()
            visible = directory / 'visible.jsonl'
            visible.write_text(''.join(canonical(value) + '\n' for value in values))
            (directory / 'receipt.json').write_text(json.dumps({
                'public_cases_sha256': 'same-query-scope', 'files': {'visible.jsonl': sha(visible)}}))
        opinions = root / 'opinions.jsonl'
        opinions.write_text(canonical({'judge_id': 'J-same', 'relevance': 0}) + '\n')
        seal = root / 'seal.json'
        seal.write_text(json.dumps({'status': 'ALL principal blind judgments closed before Gold',
            'blind_input_receipt_sha256': sha(prior / 'receipt.json'),
            'judgment_files': {str(opinions): sha(opinions)}, 'calibration_gate_passed': gate}))
        return ['reuse', '--prior-inputs', str(prior), '--current-inputs', str(current),
                '--prior-judgment-seal', str(seal), '--output', str(root / 'result')]

    def run_fixture(self, root, **kwargs):
        argv = self.fixture(root, **kwargs)
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            main()

    def test_identical_opinion_preserved_and_new_pair_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_fixture(root)
            result = root / 'result'
            self.assertEqual((result / 'reused-class-symbol-judgments.jsonl').read_bytes(),
                             (root / 'opinions.jsonl').read_bytes())
            self.assertEqual(json.loads((result / 'new-module-file.jsonl').read_text())['judge_id'], 'J-new')
            self.assertEqual(json.loads((result / 'receipt.json').read_text())['counts'],
                             {'class-symbol': {'new': 0, 'reused': 1}, 'module-file': {'new': 1, 'reused': 0}})

    def test_reused_id_with_changed_visible_query_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'changed visible input'):
                self.run_fixture(Path(tmp), changed=True)

    def test_uncalibrated_prior_judgments_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'closure or query scope'):
                self.run_fixture(Path(tmp), gate=False)


if __name__ == '__main__':
    unittest.main()
