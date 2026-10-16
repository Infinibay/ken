import numpy as np
import pytest


def fixture():
    return {'schema': 1, 'features': ['coverage'], 'trees': [
        {'feature': 0, 'threshold': .5, 'left': {'value': -.25}, 'right': {'value': .75}},
        {'value': .1},
    ]}


def test_numeric_forest_preserves_threshold_boundary_and_adds_trained_leaf_values():
    from ken.retrieval.numeric_ranker import NumericRanker

    ranker = NumericRanker.from_dict(fixture())
    scores = ranker.predict(np.array([[.1], [.5], [.500001]]))
    assert scores == pytest.approx([-.15, -.15, .85])
    assert NumericRanker.from_dict(ranker.to_dict()).predict(np.array([[.5]])).tolist() == scores[1:2].tolist()


def test_numeric_forest_rejects_incompatible_or_nonfinite_inputs():
    from ken.retrieval.numeric_ranker import NumericRanker

    invalid = fixture(); invalid['features'] = ['coverage', 'coverage']
    with pytest.raises(ValueError, match='feature'):
        NumericRanker.from_dict(invalid)
    invalid = fixture(); invalid['trees'][0]['threshold'] = float('inf')
    with pytest.raises(ValueError, match='finite'):
        NumericRanker.from_dict(invalid)
    ranker = NumericRanker.from_dict(fixture())
    with pytest.raises(ValueError, match='feature'):
        ranker.predict(np.array([[1., 2.]]))
    with pytest.raises(ValueError, match='finite'):
        ranker.predict(np.array([[float('nan')]]))


def test_forest_addition_order_remains_exact_under_cancellation():
    from ken.retrieval.numeric_ranker import NumericRanker
    # A pairwise or reordered sum would change both the score and the winner.
    model=NumericRanker.from_dict({'schema':1,'features':['value'],'trees':[
        {'value':1e16},{'value':1.}, {'value':-1e16},
        {'feature':0,'threshold':0.,'left':{'value':-.25},'right':{'value':.25}}]})
    for n in [0,1,10,128,129]:
        x=np.linspace(-1.,1.,n).reshape(n,1)
        expected=np.where(x[:,0]<=0.,-.25,.25)
        assert np.array_equal(model.predict(x),expected)


def test_forest_prediction_matches_independent_scalar_paths_for_mixed_depths():
    from ken.retrieval.numeric_ranker import NumericRanker
    rng=np.random.default_rng(73)
    def tree(depth):
        if depth==0 or rng.random()<.2:return {'value':float(rng.normal())}
        return {'feature':int(rng.integers(3)),'threshold':float(rng.normal()),
                'left':tree(depth-1),'right':tree(depth-1)}
    model=NumericRanker.from_dict({'schema':1,'features':['a','b','c'],
                                'trees':[tree(i%7) for i in range(40)]})
    before=model.to_dict();fingerprint=model.fingerprint
    for n in [0,1,10,128,129]:
        x=rng.normal(size=(n,3));expected=[]
        for row in x:
            total=0.
            for node in before['trees']:
                while 'value' not in node:node=node['left' if row[node['feature']]<=node['threshold'] else 'right']
                total+=node['value']
            expected.append(total)
        assert np.array_equal(model.predict(x),np.array(expected))
    assert model.to_dict()==before and model.fingerprint==fingerprint
