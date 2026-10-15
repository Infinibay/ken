"""Boundaries of the experimental typed-card / CPU head comparison."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ken.retrieval.model import EntityKey, Passage, Span, CodeMatch
from verifiable_pieces import SourceCatalog, piece_pool, validate_card, card_text
from ettin_cpu import numpy_head, validate_head


def passage(key, first, last, text, digest, impl=None):
    return Passage(key, Span(first, last), {'body': text, 'documentation': '',
        'signature': next(iter(text.splitlines()),'')}, digest, Span(first, last),
        implementation_start_line=impl)


class PieceCards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.text = 'class Store:\n    """Store values."""\n    def put(self, key, value):\n        self.data[key] = value\n\ndef other():\n    return None\n'
        (self.root/'store.py').write_text(self.text)
        digest = hashlib.sha256(self.text.encode()).hexdigest()
        self.cls = EntityKey('store.py','class','Store')
        self.method = EntityKey('store.py','method','Store.put','Store')
        self.fn = EntityKey('store.py','function','other')
        module = EntityKey('store.py','module',None)
        self.passages = {
            self.cls: (passage(self.cls,1,2,'class Store:\n    """Store values."""',digest),),
            self.method: (passage(self.method,3,4,'    def put(self, key, value):\n        self.data[key] = value',digest,4),),
            self.fn: (passage(self.fn,6,7,'def other():\n    return None',digest,7),),
            module: (passage(module,5,5,'',digest),)}
        # Class extent covers members, exclusive passage does not.
        from dataclasses import replace
        self.passages[self.cls] = (replace(self.passages[self.cls][0],entity_span=Span(1,4)),)
        self.catalog = SourceCatalog(self.root,self.passages)
        self.matches = [CodeMatch(self.method,2,list(self.passages[self.method]),digest),
                        CodeMatch(self.fn,1,list(self.passages[self.fn]),digest)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_class_projection_retains_supporting_method_owner(self):
        cards = piece_pool(self.matches,'class','store values by key',self.catalog)
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]['unit']['entity'],self.cls.to_dict())
        self.assertTrue(any(e['entity']==self.method.to_dict() for e in cards[0]['excerpts']))
        validate_card(cards[0],self.catalog)

    def test_symbol_module_file_are_distinct(self):
        symbols=piece_pool(self.matches,'symbol','store values',self.catalog)
        self.assertEqual(symbols[0]['unit']['entity'],self.method.to_dict())
        for kind in ('module','file'):
            cards=piece_pool(self.matches,kind,'store values',self.catalog)
            self.assertEqual(len(cards),1)
            self.assertEqual(cards[0]['unit']['target_kind'],kind)
            self.assertIsNone(cards[0]['unit']['entity'])
        self.assertEqual(piece_pool(self.matches,'class','x',self.catalog)[0]['unit']['entity']['kind'],'class')

    def test_stale_and_fabricated_content_rejected(self):
        card=piece_pool(self.matches,'symbol','values',self.catalog)[0]
        bad=json.loads(json.dumps(card));bad['excerpts'][0]['content']='invented'
        with self.assertRaises(ValueError): validate_card(bad,self.catalog)
        (self.root/'store.py').write_text(self.text+'# changed\n')
        with self.assertRaises(ValueError): validate_card(card,self.catalog)

    def test_literal_sibling_cannot_verify_a_different_symbol_or_class(self):
        sibling=piece_pool(self.matches[1:],'symbol','other',self.catalog)[0]['excerpts']
        for kind in ('symbol','class'):
            card=piece_pool(self.matches,kind,'store values',self.catalog)[0]
            card['excerpts']=sibling
            with self.assertRaisesRegex(ValueError,'unrelated owner'):
                validate_card(card,self.catalog)

    def test_ordinal_and_container_span_prevent_duplicate_name_alias(self):
        from dataclasses import replace
        first=EntityKey('store.py','class','Store',definition_ordinal=1)
        p=replace(self.passages[self.cls][0],entity=first,entity_span=Span(6,7),span=Span(6,7))
        catalog=SourceCatalog(self.root,{**self.passages,first:(p,)})
        self.assertEqual(catalog.classes[self.method],self.cls)

    def test_card_text_contains_identity_and_literal_evidence(self):
        card=piece_pool(self.matches,'class','store values',self.catalog)[0]
        text=card_text(card)
        self.assertIn('Store',text); self.assertIn('self.data[key] = value',text)
        self.assertLessEqual(len(json.dumps(card,ensure_ascii=False,sort_keys=True,separators=(',',':'))),12000)

    def test_complete_symbol_is_not_truncated_by_unrelated_file_content(self):
        card=piece_pool(self.matches,'symbol','store values',self.catalog)[0]
        self.assertFalse(card['truncated'])


class PublishedHead(unittest.TestCase):
    def test_math_and_config_contract(self):
        w={'dense':np.eye(2,dtype=np.float32),'norm_weight':np.ones(2,dtype=np.float32),
           'norm_bias':np.zeros(2,dtype=np.float32),'out':np.ones((1,2),dtype=np.float32),
           'out_bias':np.array([3],dtype=np.float32)}
        validate_head(w,2)
        scores=numpy_head(np.array([[0,1],[-2,3]],np.float32),w)
        np.testing.assert_allclose(scores,[[3],[3]],atol=1e-6)
        with self.assertRaises(ValueError): validate_head(w,3)


if __name__=='__main__': unittest.main()
