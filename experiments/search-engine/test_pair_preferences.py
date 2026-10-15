"""The fitted head minimizes equal-query squared preference error plus L2."""
import numpy as np
import pytest

from pair_preferences import LinearPreference, preference_moments, ridge_preference, training_indices


def test_training_preserves_all_positive_alternatives_and_uses_raw_priority_with_stable_ties():
    positive, negative = training_indices([0, 1, 0, 1, 0], [.4, .1, .8, .0, .8], max_negatives=2)
    np.testing.assert_array_equal(positive, [1, 3])
    np.testing.assert_array_equal(negative, [2, 4])


def test_unanswerable_training_group_remains_explicitly_empty_and_arrays_unchanged():
    labels, priority = np.zeros(2), np.array([.2, .1])
    positive, negative = training_indices(labels, priority)
    assert not len(positive)
    np.testing.assert_array_equal(negative, [0, 1])
    np.testing.assert_array_equal(labels, [0., 0.])
    np.testing.assert_array_equal(priority, [.2, .1])


@pytest.mark.parametrize('labels,priority', [([0, 2], [.1, .2]), ([0], [.1, .2]), ([1], [np.nan])])
def test_invalid_training_selection_inputs_are_rejected(labels, priority):
    with pytest.raises(ValueError):
        training_indices(labels, priority)


def test_closed_form_head_and_scores_for_one_preference():
    gram, linear = preference_moments([[1., 0.]], [[0., 1.]])
    np.testing.assert_array_equal(gram, [[1., -1.], [-1., 1.]])
    np.testing.assert_array_equal(linear, [1., -1.])
    head = ridge_preference(gram, linear, regularization=1.)
    np.testing.assert_allclose(head.weights, [1/3, -1/3], rtol=0., atol=1e-15)
    np.testing.assert_allclose(head.score([[1., 0.], [0., 1.]]), [1/3, -1/3], rtol=0., atol=1e-15)
    assert not head.weights.flags.writeable


def test_duplicate_negative_rows_do_not_give_a_query_extra_weight():
    single = preference_moments([[1., 0.]], [[0., 1.]])
    duplicate = preference_moments([[1., 0.]], [[0., 1.], [0., 1.]])
    for left, right in zip(single, duplicate, strict=True):
        np.testing.assert_array_equal(left, right)


def test_all_positive_alternatives_have_equal_weight_and_inputs_stay_intact():
    positive, negative = np.eye(2), np.array([[-1., 0.]])
    before = positive.copy()
    gram, linear = preference_moments(positive, negative)
    np.testing.assert_array_equal(gram, [[2.5, .5], [.5, .5]])
    np.testing.assert_array_equal(linear, [1.5, .5])
    np.testing.assert_array_equal(positive, before)
    head = ridge_preference(gram, linear, regularization=1.)
    np.testing.assert_allclose((gram+np.eye(2))@head.weights, linear, rtol=0., atol=1e-14)


@pytest.mark.parametrize('positive,negative', [
    ([], [[1., 0.]]), ([[1., 0.]], []),
    ([[1., 0.]], [[1.]]), ([[0., 0.]], [[1., 0.]]),
    ([[2., 0.]], [[1., 0.]]), ([[np.nan, 0.]], [[1., 0.]]),
    ([[1j, 0.]], [[1., 0.]]),
])
def test_invalid_preference_groups_fail(positive, negative):
    with pytest.raises(ValueError):
        preference_moments(positive, negative)


def test_invalid_or_singular_head_input_is_not_silently_fitted():
    for gram, linear, penalty in ((np.eye(2), [1.], 1),
                                  ([[1., 2.], [0., 1.]], [1., 1.], 1),
                                  (np.eye(2), [1., 1.], 0),
                                  (np.eye(2), [1., 1.], np.inf),
                                  (np.eye(2)*-1, [1., 1.], 1)):
        with pytest.raises(ValueError):
            ridge_preference(gram, linear, regularization=penalty)
    with pytest.raises(ValueError):
        LinearPreference(np.array([np.nan]))


def test_exported_finite_weights_cannot_silently_produce_infinite_scores():
    head = LinearPreference(np.full(768, np.finfo(np.float64).max))
    with pytest.raises(ValueError, match='finite'):
        head.score(np.ones((1, 768))/np.sqrt(768))
