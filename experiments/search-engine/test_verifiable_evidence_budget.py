"""Evidence capacity belongs to complete useful source, not fixed owner quotas."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from ken.retrieval.model import CodeMatch, EntityKey, Passage, Span
from verifiable_pieces import SourceCatalog, piece_pool, validate_card


def catalog_for(root, lines, definitions):
    text = '\n'.join(lines) + '\n'
    (root / 'record.py').write_text(text)
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    owners = {}
    for key, start, end, implementation, extent in definitions:
        parts = []
        for a in range(start, end + 1, 20):
            b = min(end, a + 19)
            parts.append(Passage(key, Span(a, b),
                {'body': '\n'.join(lines[a - 1:b]), 'documentation': '', 'signature': lines[start - 1]},
                source_hash, Span(*extent), implementation_start_line=implementation))
        owners[key] = tuple(parts)
    catalog = SourceCatalog(root, owners)
    matches = [CodeMatch(key, 10 - i, list(owners[key]), source_hash)
               for i, (key, *_rest) in enumerate(definitions) if key.kind in {'method', 'function'}]
    return catalog, matches


class EvidenceCapacity(unittest.TestCase):
    def test_class_keeps_entire_relevant_member_when_it_fits(self):
        lines = ['class Record:', '    """A validated stored record."""',
                 '    def validate(self, name, version):']
        lines += ['        values = self.values'] * 42
        lines += ['        if version != self.version:', '            raise ValueError("wrong version")',
                  '        return name == self.name', '    def unrelated(self):', '        return 0']
        cls = EntityKey('record.py', 'class', 'Record')
        method = EntityKey('record.py', 'method', 'Record.validate', 'Record')
        other = EntityKey('record.py', 'method', 'Record.unrelated', 'Record')
        with tempfile.TemporaryDirectory() as tmp:
            catalog, matches = catalog_for(Path(tmp), lines, [
                (method, 3, 48, 4, (3, 48)), (other, 49, 50, 50, (49, 50)),
                (cls, 1, 2, None, (1, 50))])
            card = piece_pool(matches, 'class', 'validate the stored record name and version', catalog)[0]
            quoted = '\n'.join(e['content'] for e in card['excerpts'])
            self.assertIn('raise ValueError("wrong version")', quoted)
            self.assertIn('return name == self.name', quoted)
            self.assertIn('def validate(', quoted)
            validate_card(card, catalog)

    def test_file_keeps_function_contract_and_tail_before_unrelated_header(self):
        lines = ['# Legal notice'] * 20 + ['def validate(name, version):',
            '    """Reject names and versions inconsistent with a stored record."""']
        lines += ['    values = load_values()'] * 40
        lines += ['    if version != values.version:', '        raise ValueError("wrong version")',
                  '    return name == values.name']
        key = EntityKey('record.py', 'function', 'validate')
        module = EntityKey('record.py', 'module', None)
        with tempfile.TemporaryDirectory() as tmp:
            catalog, matches = catalog_for(Path(tmp), lines, [
                (key, 21, 65, 23, (21, 65)), (module, 1, 20, None, (1, 65))])
            for kind in ('module', 'file'):
                with self.subTest(kind=kind):
                    card = piece_pool(matches, kind, 'reject inconsistent record name and version', catalog)[0]
                    quoted = '\n'.join(e['content'] for e in card['excerpts'])
                    self.assertIn('Reject names and versions inconsistent', quoted)
                    self.assertIn('return name == values.name', quoted)
                    validate_card(card, catalog)

    def test_large_member_uses_available_capacity_and_keeps_owner_boundaries(self):
        lines = ['class Record:', '    def validate(self, name):']
        lines += ['        check_name(name)'] * 70
        cls = EntityKey('record.py', 'class', 'Record')
        key = EntityKey('record.py', 'method', 'Record.validate', 'Record')
        with tempfile.TemporaryDirectory() as tmp:
            catalog, matches = catalog_for(Path(tmp), lines, [
                (key, 2, 72, 3, (2, 72)), (cls, 1, 1, None, (1, 72))])
            card = piece_pool(matches, 'class', 'check the supplied name', catalog)[0]
            self.assertTrue(card['truncated'])
            self.assertEqual(sum(e['end_line'] - e['start_line'] + 1 for e in card['excerpts']), 64)
            validate_card(card, catalog)


if __name__ == '__main__':
    unittest.main()
