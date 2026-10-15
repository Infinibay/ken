"""Agreement preserves signed contrasts rather than renormalizing them."""
import numpy as np
import pytest

from semantic_agreement import agreement_features


def test_same_opposed_and_orthogonal_candidate_mean_different_things():
    query = np.array([.6, -.2])
    owners = np.array([[.6, -.2], [-.6, .2], [0., 0.]])
    actual = agreement_features(query, owners)
    np.testing.assert_allclose(actual, [
        [.6, -.2, .36, .04, 0., 0.],
        [-.6, .2, -.36, -.04, 1.2, .4],
        [0., 0., 0., 0., .6, .2],
    ], rtol=0., atol=1e-15)


def test_zero_query_keeps_candidate_information_without_inventing_direction():
    np.testing.assert_array_equal(agreement_features([0., 0.], [[.3, -.4]]),
                                  [[.3, -.4, 0., 0., .3, .4]])


def test_empty_candidates_are_supported_and_inputs_are_not_mutated_or_aliased():
    query, owners = np.array([.5, -.5]), np.array([[1., 0.]])
    before_q, before_o = query.copy(), owners.copy()
    result = agreement_features(query, owners)
    np.testing.assert_array_equal(query, before_q)
    np.testing.assert_array_equal(owners, before_o)
    result[0, 0] = 9
    np.testing.assert_array_equal(owners, before_o)
    assert agreement_features(query, np.empty((0, 2))).shape == (0, 6)


@pytest.mark.parametrize('query,owners', [
    ([[.1, .2]], [[.1, .2]]),
    ([.1, .2], [.1, .2]),
    ([.1], [[.1, .2]]),
    ([], np.empty((2, 0))),
    ([np.nan], [[0.]]),
    ([0.], [[np.inf]]),
    ([0j], [[0.]]),
    (['0.1'], [[0.]]),
    ([1.01], [[0.]]),
    ([0.], [[-1.01]]),
])
def test_incompatible_or_non_cosine_coordinates_are_rejected(query, owners):
    with pytest.raises(ValueError):
        agreement_features(query, owners)


@pytest.mark.parametrize('dtype', [np.int8, np.int16, np.int32, np.int64])
def test_minimum_signed_integer_cannot_escape_cosine_range(dtype):
    smallest = np.array([np.iinfo(dtype).min], dtype=dtype)
    with pytest.raises(ValueError):
        agreement_features(smallest, [[0.]])
    with pytest.raises(ValueError):
        agreement_features([0.], smallest[None, :])


def test_integer_cosine_endpoints_are_valid():
    np.testing.assert_array_equal(agreement_features([1, -1], [[1, 0]]),
                                  [[1., 0., 1., 0., 0., 1.]])
