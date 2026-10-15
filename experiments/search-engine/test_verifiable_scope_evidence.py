"""Source scopes compose owned members without hiding provenance or context."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from ken.retrieval.model import CodeMatch, EntityKey, Passage, Span
from verifiable_pieces import SourceCatalog, piece_pool, validate_card


def catalog_for(root, lines, specs):
    text='\n'.join(lines)+'\n';(root/'sample.py').write_text(text)
    sha=hashlib.sha256(text.encode()).hexdigest();owners={}
    for key,ranges,extent in specs:
        owners[key]=tuple(Passage(key,Span(a,b),{'body':'\n'.join(lines[a-1:b]),
            'documentation':'','signature':lines[extent[0]-1]},sha,Span(*extent)) for a,b in ranges)
    return SourceCatalog(root,owners),lambda key:CodeMatch(key,1,list(owners[key]),sha)


def class_fixture(root):
    lines=['class Store:', '    """A mutable key-value store."""',
           '    def put(self, key, value):','        self.data[key] = value',
           '    def get(self, key):','        return self.data[key]',
           '    def clear(self):','        self.data.clear()', '', 'def unrelated():','    return None']
    cls=EntityKey('sample.py','class','Store')
    put=EntityKey('sample.py','method','Store.put','Store')
    get=EntityKey('sample.py','method','Store.get','Store')
    clear=EntityKey('sample.py','method','Store.clear','Store')
    other=EntityKey('sample.py','function','unrelated')
    catalog,match=catalog_for(root,lines,[(cls,[(1,2)],(1,8)),(put,[(3,4)],(3,4)),
        (get,[(5,6)],(5,6)),(clear,[(7,8)],(7,8)),(other,[(10,11)],(10,11))])
    return catalog,match,cls,put,other


def nested_fixture(root):
    lines=['def test_instances():','    class Item:', '        def __init__(self, value):',
           '            self.value = value','', '    first = Item(1)', '    second = Item(2)',
           '    assert first.value != second.value']
    test=EntityKey('sample.py','function','test_instances')
    cls=EntityKey('sample.py','class','test_instances.Item','test_instances')
    init=EntityKey('sample.py','method','test_instances.Item.__init__','test_instances.Item')
    catalog,match=catalog_for(root,lines,[(test,[(1,1),(6,8)],(1,8)),
        (cls,[(2,2)],(2,4)),(init,[(3,4)],(3,4))])
    return catalog,match,test,cls,init


class LexicalScopeEvidence(unittest.TestCase):
    def test_short_class_shows_all_methods_with_explicit_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,match,cls,put,_=class_fixture(Path(tmp))
            card=piece_pool([match(put)],'class','put get and clear stored values',catalog)[0]
            self.assertEqual(card['unit']['entity'],cls.to_dict())
            self.assertFalse(card['truncated'])
            self.assertEqual(len(card['excerpts']),1)
            excerpt=card['excerpts'][0]
            self.assertEqual(excerpt['scope'],'lexical_container')
            self.assertIn('self.data.clear()',excerpt['content'])
            self.assertEqual(len(excerpt['included_entities']),3)
            validate_card(card,catalog)

    def test_nested_class_file_evidence_keeps_constructor_and_enclosing_assertions(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,match,test,cls,_=nested_fixture(Path(tmp))
            card=piece_pool([match(cls)],'file','test independent values across instances',catalog)[0]
            self.assertIsNone(card['unit']['entity'])
            self.assertEqual(len(card['excerpts']),1)
            excerpt=card['excerpts'][0]
            self.assertEqual(excerpt['entity'],test.to_dict())
            self.assertIn('self.value = value',excerpt['content'])
            self.assertIn('assert first.value != second.value',excerpt['content'])
            validate_card(card,catalog)

    def test_outer_symbol_quotes_nested_code_without_exclusive_misattribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,match,test,cls,init=nested_fixture(Path(tmp))
            card=piece_pool([match(test)],'symbol','construct independent instances and assert values',catalog)[0]
            self.assertFalse(card['truncated'])
            self.assertEqual(len(card['excerpts']),1)
            self.assertEqual(card['excerpts'][0]['scope'],'lexical_container')
            members=card['excerpts'][0]['included_entities']
            self.assertIn(cls.to_dict(),members);self.assertIn(init.to_dict(),members)
            validate_card(card,catalog)

    def test_forged_or_missing_member_attribution_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,match,_,put,other=class_fixture(Path(tmp))
            card=piece_pool([match(put)],'class','put get and clear values',catalog)[0]
            for members in [[],[other.to_dict()]]:
                bad=deepcopy(card);bad['excerpts'][0]['scope']='lexical_container'
                bad['excerpts'][0]['included_entities']=members
                with self.assertRaisesRegex(ValueError,'lexical scope'):
                    validate_card(bad,catalog)


if __name__=='__main__':unittest.main()
