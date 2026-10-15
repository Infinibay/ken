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
