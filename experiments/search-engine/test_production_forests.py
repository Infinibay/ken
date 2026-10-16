import unittest
import numpy as np
from production_forests import mean_forests
from ken.retrieval.numeric_ranker import NumericRanker


def model(trees, features=('x',)):
    return NumericRanker.from_dict({'schema':1,'features':features,'trees':trees})


class MeanForest(unittest.TestCase):
    def test_equal_model_weight_is_not_equal_tree_weight(self):
        a=model([{'value':2.}])
        b=model([{'feature':0,'threshold':0.,'left':{'value':4.},'right':{'value':8.}}, {'value':6.}])
        merged=mean_forests([a,b])
        # Mean of complete model scores: (2+10)/2 and (2+14)/2.
        np.testing.assert_array_equal(merged.predict(np.array([[-1.],[1.]])),[6.,8.])
        np.testing.assert_array_equal(a.predict(np.array([[-1.],[1.]])),[2.,2.])
        np.testing.assert_array_equal(b.predict(np.array([[-1.],[1.]])),[10.,14.])

    def test_refuses_incompatible_feature_identity(self):
        with self.assertRaisesRegex(ValueError,'feature'):
            mean_forests([model([{'value':1.}]),model([{'value':1.}],features=('y',))])

    def test_refuses_no_models(self):
        with self.assertRaisesRegex(ValueError,'nonempty'):
            mean_forests([])


if __name__=='__main__':unittest.main()
