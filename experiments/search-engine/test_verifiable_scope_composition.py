"""File/module evidence composes complementary complete lexical scopes."""
from pathlib import Path
import tempfile
import unittest
from ken.retrieval.model import EntityKey
from verifiable_pieces import EvidenceCardBuilder, piece_pool, validate_card
from test_verifiable_scope_evidence import catalog_for, class_fixture


class ComplementaryScopes(unittest.TestCase):
    def test_sibling_factories_keep_both_predicates_and_collapse_duplicates(self):
        lines=['def allow(kind):','    """Build an inclusion predicate from a type."""',
               '    def predicate(value):','        return isinstance(value, kind)',
               '    return predicate','', 'def deny(kind):',
               '    """Build an exclusion predicate from a type."""',
               '    def predicate(value):','        return not isinstance(value, kind)',
               '    return predicate']
        allow=EntityKey('sample.py','function','allow')
        yes=EntityKey('sample.py','function','allow.predicate','allow')
        deny=EntityKey('sample.py','function','deny')
        no=EntityKey('sample.py','function','deny.predicate','deny')
        for kind in ('file','module'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                catalog,match=catalog_for(Path(tmp),lines,[(allow,[(1,2),(5,5)],(1,5)),
                    (yes,[(3,4)],(3,4)),(deny,[(7,8),(11,11)],(7,11)),(no,[(9,10)],(9,10))])
                card=piece_pool([match(yes),match(allow),match(no)],kind,
                    'construct inclusion and exclusion predicates from a type',catalog)[0]
                self.assertEqual([e['entity'] for e in card['excerpts']],
                                 [allow.to_dict(),deny.to_dict()])
                self.assertTrue(all(e.get('scope')=='lexical_container' for e in card['excerpts']))
                text='\n'.join(e['content'] for e in card['excerpts'])
                self.assertIn('return isinstance(value, kind)',text)
                self.assertIn('return not isinstance(value, kind)',text)
                validate_card(card,catalog)

    def test_complete_scope_can_be_appended_without_duplicating_existing_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,_,cls,_,other=class_fixture(Path(tmp))
            card={'unit':{'target_kind':'file','path':'sample.py','entity':None,'module_name':None},
                  'source_hash':catalog.hashes['sample.py'],'excerpts':[],'truncated':False}
            builder=EvidenceCardBuilder(card,catalog)
            builder.definition(other,'return a value')
            builder.definition(cls,'put get and clear')
            builder.definition(cls,'put get and clear')
            self.assertEqual(len(card['excerpts']),2)
            self.assertEqual(card['excerpts'][1].get('scope'),'lexical_container')
            self.assertIn('self.data.clear()',card['excerpts'][1]['content'])
            self.assertEqual(builder.remaining_lines,54)
            validate_card(card,catalog)


if __name__=='__main__':unittest.main()
