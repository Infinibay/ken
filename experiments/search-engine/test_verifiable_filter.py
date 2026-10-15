import unittest
from verifiable_filter import conservative_threshold,filter_order


class ConservativeFilter(unittest.TestCase):
    def test_threshold_protects_incomplete_but_correct_units(self):
        scores={'complete':4.0,'sparse':-2.0,'wrong':-3.0}
        labels=[{'card_id':'complete','variant':'sufficient'},
                {'card_id':'sparse','variant':'identity_only_insufficient'},
                {'card_id':'wrong','variant':'faithful_plausible_distractor'}]
        threshold=conservative_threshold(scores,labels)
        self.assertEqual(threshold,-2.0)
        self.assertEqual(filter_order([-2.0,-3.0,4.0],threshold),[2,0])

    def test_monotone_filter_cannot_improve_top_rank(self):
        scores=[1.0,5.0,2.0]
        self.assertEqual(filter_order(scores,2.0)[0],1)
        self.assertEqual(filter_order(scores,6.0),[])

    def test_missing_protected_score_is_not_ignored(self):
        with self.assertRaises(ValueError):
            conservative_threshold({},[{'card_id':'positive','variant':'sufficient'}])


if __name__=='__main__':unittest.main()
