import numpy as np
import pytest


def test_alignment_measures_coverage_of_every_query_term_with_rarity_weights():
    from ken.retrieval.alignment import TermAlignment

    alignment = TermAlignment(np.array([[1., 0.], [0., 1.]]), np.array([1., 3.]))
    partial = alignment.coverage(np.array([[1., 0.]]))
    complete = alignment.coverage(np.array([[1., 0.], [0., 1.]]))
    assert partial.mean == .5
    assert partial.minimum == 0.
    assert partial.weighted == .25
    assert partial.quartile == .25
    assert partial.above50 == .5
    assert complete.weighted == 1.
    assert complete.minimum == 1.
    # Repetition cannot invent evidence for the missing term.
    assert alignment.coverage(np.array([[1., 0.]] * 9)) == partial


def test_empty_terms_have_finite_zero_coverage_and_invalid_weights_are_rejected():
    from ken.retrieval.alignment import TermAlignment

    alignment = TermAlignment(np.array([[1., 0.]]), np.array([1.]))
    assert alignment.coverage(np.empty((0, 2))).weighted == 0.
    assert TermAlignment(np.empty((0, 2)), np.empty(0)).coverage(np.array([[1., 0.]])).mean == 0.
    with pytest.raises(ValueError, match='weights'):
        TermAlignment(np.array([[1., 0.]]), np.array([-1.]))
