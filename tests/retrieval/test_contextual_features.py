import numpy as np
import pytest

from ken.retrieval.model import Candidate, EntityKey


def candidates(original, expanded):
    return [Candidate(EntityKey('source.py', 'function', f'operation_{i}'), [],
        {'cosine_code_original': a, 'cosine_code_expanded': b})
        for i, (a, b) in enumerate(zip(original, expanded, strict=True))]


def test_contextual_scores_keep_raw_values_and_stable_pool_relative_ranks():
    from ken.retrieval.contextual_features import contextual_features, CONTEXTUAL_FEATURES

    rows = candidates([.2, -.2, .2], [.1, .8, .4])
    result = contextual_features(rows)
    assert result.names == CONTEXTUAL_FEATURES
    np.testing.assert_array_equal(result.values[:, 0], [.2, -.2, .2])
    np.testing.assert_array_equal(result.values[:, 1], [0., -.4, 0.])
    np.testing.assert_array_equal(result.values[:, 2], [1., 0., 1.])
    np.testing.assert_array_equal(result.values[:, 3], [1., 1/3, 1/2])
    np.testing.assert_array_equal(result.values[:, 7], [1/3, 1., 1/2])


def test_empty_and_constant_context_scores_do_not_invent_alignment():
    from ken.retrieval.contextual_features import contextual_features

    assert contextual_features([]).values.shape == (0, 8)
    result = contextual_features(candidates([0., 0.], [.4, .4])).values
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(result[:, [1, 2, 5, 6]], np.zeros((2, 4)))
    np.testing.assert_array_equal(result[:, 3], [1., .5])


def test_missing_contextual_evidence_is_rejected_instead_of_becoming_a_zero_score():
    from ken.retrieval.contextual_features import contextual_features

    rows = candidates([.2, .4], [.4, .6])
    del rows[1].signals['cosine_code_expanded']
    with pytest.raises(ValueError, match='contextual'):
        contextual_features(rows)
    rows[1].signals['cosine_code_expanded'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        contextual_features(rows)
