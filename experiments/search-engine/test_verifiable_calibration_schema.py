import unittest
from verifiable_calibration_schema import normalize_row


class CalibrationVocabulary(unittest.TestCase):
    def test_aliases_preserve_all_labels_and_evidence(self):
        for alias, name in [('sparse', 'identity_only_insufficient'),
                            ('distractor', 'faithful_plausible_distractor'),
                            ('sufficient', 'sufficient')]:
            row = {'variant': alias, 'card_id': 'synthetic', 'expected_relevance': 1,
                   'expected_sufficiency': 0, 'expected_pass': False, 'source_hashes': {'a.py': 'pinned'}}
            self.assertEqual(normalize_row(row), {**row, 'variant': name})
            self.assertEqual(row['variant'], alias)

    def test_canonical_variants_stay_identical_and_unknown_cannot_be_guessed(self):
        for name in ('sufficient', 'identity_only_insufficient', 'faithful_plausible_distractor'):
            row = {'variant': name, 'card_id': 'synthetic'}
            self.assertEqual(normalize_row(row), row)
        with self.assertRaisesRegex(ValueError, 'unknown calibration variant'):
            normalize_row({'variant': 'ambiguous'})


if __name__ == '__main__':
    unittest.main()
