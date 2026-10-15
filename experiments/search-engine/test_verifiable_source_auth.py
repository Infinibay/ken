"""Authenticity is independent of how a renderer selects supporting evidence."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from ken.retrieval.model import EntityKey, Passage, Span
from verifiable_pieces import SourceCatalog, validate_card
from verifiable_source_auth import authenticate_card


class AttributedEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        sources = {'api.py': 'def save(x):\n    return persist(x)\n',
                   'storage.py': 'def persist(x):\n    disk.write(x)\n'}
        owners = {}
        self.keys = {}
        for path, text in sources.items():
            (root / path).write_text(text)
            key = EntityKey(path, 'function', 'save' if path == 'api.py' else 'persist')
            self.keys[path] = key
            source_hash = hashlib.sha256(text.encode()).hexdigest()
            owners[key] = (Passage(key, Span(1, 2), {'body': text}, source_hash, Span(1, 2)),)
        self.catalog = SourceCatalog(root, owners)
        key = self.keys['api.py']
        self.card = {'unit': {'target_kind': 'symbol', 'path': key.path,
                              'entity': key.to_dict(), 'module_name': None},
                     'source_hash': self.catalog.hashes[key.path], 'excerpts': [], 'truncated': False}
        for path in sources:
            self.card['excerpts'].append({'role': 'implementation', 'path': path,
                'source_hash': self.catalog.hashes[path], 'entity': self.keys[path].to_dict(),
                'start_line': 1, 'end_line': 2, 'content': '\n'.join(sources[path].splitlines())})

    def tearDown(self):
        self.tmp.cleanup()

    def test_attributed_caller_and_helper_authenticate_without_changing_renderer(self):
        authenticate_card(self.card, self.catalog)
        with self.assertRaises(ValueError):
            validate_card(self.card, self.catalog)

    def test_faithful_but_unlinked_quote_is_authentic_not_proof_of_relevance(self):
        self.card['excerpts'] = self.card['excerpts'][1:]
        authenticate_card(self.card, self.catalog)
        from verifiable_grading import blind_pass
        self.assertFalse(blind_pass(self.card, [{'id': 'F1', 'text': 'save delegates persistence'}],
            {'relevance': 1, 'sufficiency': 0, 'requirements': []}))

    def test_false_owner_changed_helper_and_fabricated_quotes_fail(self):
        bad = copy.deepcopy(self.card)
        bad['excerpts'][1]['entity'] = self.keys['api.py'].to_dict()
        with self.assertRaises(ValueError):
            authenticate_card(bad, self.catalog)
        bad = copy.deepcopy(self.card)
        bad['excerpts'][1]['content'] = 'disk.flush(x)'
        with self.assertRaises(ValueError):
            authenticate_card(bad, self.catalog)
        (self.catalog.root / 'storage.py').write_text('changed\n')
        with self.assertRaises(ValueError):
            authenticate_card(self.card, self.catalog)

    def test_primary_identity_and_budget_remain_required(self):
        bad = copy.deepcopy(self.card)
        bad['unit']['entity']['qualname'] = 'missing'
        with self.assertRaises(ValueError):
            authenticate_card(bad, self.catalog)
        bad = copy.deepcopy(self.card)
        bad['excerpts'] *= 3
        with self.assertRaises(ValueError):
            authenticate_card(bad, self.catalog)


if __name__ == '__main__':
    unittest.main()
