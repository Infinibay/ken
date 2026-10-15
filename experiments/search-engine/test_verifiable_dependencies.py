"""A visible call may bring its proven local definition into the response."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from ken.retrieval.model import CodeMatch, EntityKey, Passage, Span
from verifiable_pieces import SourceCatalog, piece_pool, validate_card
from verifiable_dependencies import LocalCallEvidence, enrich_card


def fixture(root, *, shadow=False):
    lines = ['def ensure(value):', '    if value is None:', '        raise ValueError("missing value")',
             '    return value', '', 'def store(value' + (', ensure' if shadow else '') + '):',
             '    ensure(value)', '    return [value]', '', 'def unrelated(value):', '    return 42']
    text = '\n'.join(lines) + '\n'
    (root / 'sample.py').write_text(text)
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    helper = EntityKey('sample.py', 'function', 'ensure')
    caller = EntityKey('sample.py', 'function', 'store')
    other = EntityKey('sample.py', 'function', 'unrelated')
    owners = {key: (Passage(key, Span(a,b), {'body': '\n'.join(lines[a-1:b]),
        'documentation': '', 'signature': lines[a-1]}, source_hash, Span(a,b),
        implementation_start_line=a+1),) for key,a,b in [(helper,1,4),(caller,6,8),(other,10,11)]}
    catalog = SourceCatalog(root, owners)
    card = piece_pool([CodeMatch(caller,1,list(owners[caller]),source_hash)], 'symbol',
        'store a supplied value, rejecting a missing value', catalog)[0]
    return catalog, card, helper, caller, other


class LocalDependencyEvidence(unittest.TestCase):
    def test_caller_stays_the_result_and_helper_is_a_verified_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, card, helper, caller, _ = fixture(Path(tmp))
            dependencies = LocalCallEvidence(catalog)
            result = enrich_card(card, 'store a value, rejecting a missing value', catalog, dependencies)
            self.assertEqual(result['unit'], card['unit'])
            self.assertEqual(len(card['excerpts']), 1)  # Input pools stay immutable.
            support = next(e for e in result['excerpts'] if e['entity'] == helper.to_dict())
            self.assertIn('raise ValueError("missing value")', support['content'])
            self.assertEqual(support['dependency']['caller'], caller.to_dict())
            validate_card(result, catalog, dependencies=dependencies)
            with self.assertRaisesRegex(ValueError, 'dependency resolver'):
                validate_card(result, catalog)

    def test_callable_parameter_shadowing_does_not_select_same_named_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, card, *_ = fixture(Path(tmp), shadow=True)
            result = enrich_card(card, 'store a value, rejecting a missing value', catalog, LocalCallEvidence(catalog))
            self.assertEqual(result, card)

    def test_tampered_callee_or_callsite_cannot_bypass_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, card, _, _, other = fixture(Path(tmp))
            dependencies = LocalCallEvidence(catalog)
            result = enrich_card(card, 'reject a missing value', catalog, dependencies)
            bad = deepcopy(result)
            bad['excerpts'][-1].update(entity=other.to_dict(), start_line=10, end_line=11,
                content='def unrelated(value):\n    return 42')
            with self.assertRaises(ValueError): validate_card(bad, catalog, dependencies=dependencies)
            bad = deepcopy(result)
            # Keep authentic source but remove the call from the primary evidence.
            bad['excerpts'][0].update(start_line=8, end_line=8, content='    return [value]')
            with self.assertRaisesRegex(ValueError, 'visible call'):
                validate_card(bad, catalog, dependencies=dependencies)

    def test_source_change_invalidates_a_cached_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, card, *_ = fixture(Path(tmp))
            dependencies = LocalCallEvidence(catalog)
            enrich_card(card, 'reject a missing value', catalog, dependencies)
            (Path(tmp) / 'sample.py').write_text('def ensure(value):\n    return value\n')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                enrich_card(card, 'reject a missing value', catalog, dependencies)

    def test_resolution_from_another_source_catalog_cannot_authorize_support(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            catalog, card, *_ = fixture(Path(tmp))
            resolver_catalog, *_ = fixture(Path(other))
            dependencies = LocalCallEvidence(resolver_catalog)
            with self.assertRaisesRegex(ValueError, 'different source catalog'):
                enrich_card(card, 'reject a missing value', catalog, dependencies)

    def test_instance_call_resolves_to_its_own_class_without_a_name_guess(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lines = ['class Left:', '    def check(self, value):', '        return False',
                     'class Right:', '    def check(self, value):', '        return value is not None',
                     '    def store(self, value):', '        return self.check(value)']
            text = '\n'.join(lines) + '\n';(root/'sample.py').write_text(text)
            source_hash = hashlib.sha256(text.encode()).hexdigest()
            owners = {}
            for name,a,b in [('Left.check',2,3),('Right.check',5,6),('Right.store',7,8)]:
                key = EntityKey('sample.py','method',name,name.split('.')[0])
                owners[key] = (Passage(key, Span(a,b),{'body':'\n'.join(lines[a-1:b]),
                    'documentation':'','signature':lines[a-1]},source_hash,Span(a,b),implementation_start_line=a+1),)
            catalog = SourceCatalog(root,owners);caller = list(owners)[-1]
            card = piece_pool([CodeMatch(caller,1,list(owners[caller]),source_hash)],'symbol','store a checked value',catalog)[0]
            dependencies = LocalCallEvidence(catalog)
            result = enrich_card(card,'store a checked value',catalog,dependencies)
            supports = [e['entity']['qualname'] for e in result['excerpts'] if 'dependency' in e]
            self.assertEqual(supports,['Right.check'])
            validate_card(result,catalog,dependencies=dependencies)

    def test_unchanged_card_when_no_line_or_excerpt_capacity_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog, card, *_ = fixture(Path(tmp))
            # Four repeated excerpts quote the original three lines; the caller
            # is still authenticated and the budget has no free excerpt slot.
            card['excerpts'] = [deepcopy(card['excerpts'][0]) for _ in range(4)]
            dependencies = LocalCallEvidence(catalog)
            self.assertEqual(enrich_card(card, 'reject a missing value', catalog, dependencies), card)


if __name__ == '__main__':
    unittest.main()
