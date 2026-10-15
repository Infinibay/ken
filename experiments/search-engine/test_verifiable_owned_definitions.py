"""A response follows source ownership rather than retrieval fragment boundaries."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from ken.retrieval.model import CodeMatch, EntityKey, Passage, Span
from verifiable_pieces import SourceCatalog, piece_pool, validate_card


def fixture(root, count, ranges=None):
    lines = ['def transform(value):'] + [f'    x{i} = value' for i in range(2, count)] + ['    return value']
    text = '\n'.join(lines) + '\n'
    (root / 'sample.py').write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    key = EntityKey('sample.py', 'function', 'transform')
    ranges = ranges or [(a, min(a + 19, count)) for a in range(1, count + 1, 20)]
    passages = [Passage(key, Span(a, b), {'body': '\n'.join(lines[a - 1:b]),
        'documentation': '', 'signature': lines[0]}, digest, Span(1, count),
        implementation_start_line=2) for a, b in ranges]
    catalog = SourceCatalog(root, {key: tuple(passages)})
    match = CodeMatch(key, 1.0, passages, digest)
    return catalog, match


class OwnedDefinitionEvidence(unittest.TestCase):
    def test_short_complete_definition_crosses_index_fragments_without_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, match = fixture(Path(tmp), 64)
            card = piece_pool([match], 'symbol', 'transform value', catalog)[0]
            quoted = {line for e in card['excerpts'] for line in range(e['start_line'], e['end_line'] + 1)}
            self.assertEqual(quoted, set(range(1, 65)))
            self.assertFalse(card['truncated'])
            validate_card(card, catalog)

    def test_long_definition_window_is_not_limited_by_twenty_line_index_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, match = fixture(Path(tmp), 65)
            card = piece_pool([match], 'symbol', 'transform value', catalog)[0]
            lengths = [e['end_line'] - e['start_line'] + 1 for e in card['excerpts'] if e['role'] == 'implementation']
            self.assertGreaterEqual(max(lengths), 36)
            self.assertLessEqual(sum(e['end_line'] - e['start_line'] + 1 for e in card['excerpts']), 64)
            self.assertTrue(card['truncated'])
            validate_card(card, catalog)

    def test_overlapping_passages_do_not_spend_budget_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, match = fixture(Path(tmp), 64, [(1, 25), (20, 45), (40, 64)])
            card = piece_pool([match], 'symbol', 'transform value', catalog)[0]
            self.assertFalse(card['truncated'])
            self.assertEqual(sum(e['end_line'] - e['start_line'] + 1 for e in card['excerpts']), 64)

    def test_excluded_nested_owner_is_not_attributed_to_its_caller(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, match = fixture(Path(tmp), 12, [(1, 4), (9, 12)])
            card = piece_pool([match], 'symbol', 'transform value', catalog)[0]
            quoted = {line for e in card['excerpts'] for line in range(e['start_line'], e['end_line'] + 1)}
            self.assertEqual(quoted, set(range(1, 5)) | set(range(9, 13)))
            self.assertTrue(card['truncated'])
            validate_card(card, catalog)


if __name__ == '__main__':
    unittest.main()
