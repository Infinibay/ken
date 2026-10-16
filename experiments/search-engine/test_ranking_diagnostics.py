"""Trace grouping follows the same canonical piece projection as retrieval."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from ranking_diagnostics import piece_order
from test_verifiable_scope_evidence import class_fixture


class PieceDiagnostics(unittest.TestCase):
    def test_class_and_file_representatives_preserve_actual_owner_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog,_,cls,put,other=class_fixture(Path(tmp))
            owners=[{'path':key.path,'entity':key.to_dict(),'proposal_index':index,
                     'rank':rank,'score':score} for index,(key,rank,score) in enumerate([
                         (put,2,.5),(cls,1,.8),(other,3,.1)])]
            original=deepcopy(owners)
            classes=piece_order(owners,'class',catalog)
            self.assertEqual(len(classes),1)
            self.assertEqual(classes[0]['unit']['entity'],cls.to_dict())
            self.assertEqual(classes[0]['representative_proposal_index'],1)
            self.assertEqual(classes[0]['owner_proposal_indices'],[1,0])
            files=piece_order(owners,'file',catalog)
            self.assertEqual(files[0]['unit']['path'],'sample.py')
            self.assertEqual(files[0]['owner_proposal_indices'],[1,0,2])
            symbols=piece_order(owners,'symbol',catalog)
            self.assertEqual([p['unit']['entity'] for p in symbols],[put.to_dict(),other.to_dict()])
            self.assertEqual(owners,original)


if __name__=='__main__':unittest.main()
