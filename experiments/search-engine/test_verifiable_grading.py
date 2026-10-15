import unittest
from verifiable_grading import identity_hit,blind_pass


class GradeUnits(unittest.TestCase):
    def setUp(self):
        self.unit={'target_kind':'symbol','path':'cache.py','entity':{
            'kind':'method','qualname':'Cache.get','owner':'Cache','definition_ordinal':0},
            'module_name':None}
        self.card={'unit':self.unit,'excerpts':[{'content':'return self.data[key]'}]}

    def test_exact_unit_includes_path_kind_owner_ordinal(self):
        self.assertTrue(identity_hit(self.card,[self.unit]))
        for field,value in [('path','other.py'),('target_kind','file')]:
            wrong={**self.unit,field:value};self.assertFalse(identity_hit(self.card,[wrong]))
        wrong={**self.unit,'entity':{**self.unit['entity'],'definition_ordinal':1}}
        self.assertFalse(identity_hit(self.card,[wrong]))

    def test_visible_evidence_for_every_public_facet(self):
        facets=[{'id':'F1','text':'read stored value'}]
        judgment={'relevance':2,'sufficiency':2,'abstain':False,'requirements':[
            {'facet_id':'F1','state':'supported','evidence':[{'excerpt':0,'quote':'self.data[key]'}]}]}
        self.assertTrue(blind_pass(self.card,facets,judgment))
        judgment['requirements'][0]['evidence'][0]['quote']='not visible'
        self.assertFalse(blind_pass(self.card,facets,judgment))
        judgment['requirements']=[]
        self.assertFalse(blind_pass(self.card,facets,judgment))

    def test_wrong_relevance_cannot_be_compensated_by_complete_evidence(self):
        self.assertFalse(blind_pass(self.card,[],{'relevance':0,'sufficiency':2,'requirements':[]}))


if __name__=='__main__':unittest.main()
