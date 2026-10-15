"""Batch source views without changing query coverage or empty-view semantics."""
import numpy as np
import pytest

from ken.retrieval.alignment import TermAlignment, TermCoverage


def test_complete_partial_and_empty_views_keep_their_individual_meaning():
    alignment = TermAlignment(np.eye(2, dtype=np.float32), np.array([1., 3.]))
    maxima = np.array([[1., 1.], [1., 0.], [-np.inf, -np.inf]], dtype=np.float32)
    rows = alignment.summarize_maxima(maxima, present=np.array([True, True, False]))
    assert rows == (
        TermCoverage(1., 1., 1., 1., 1., 1.),
        TermCoverage(.5, 0., .25, .5, .5, .25),
        TermCoverage(),
    )


def test_negative_matches_are_not_clipped_and_zero_weights_remain_finite():
    alignment = TermAlignment(np.eye(2), np.array([1., 3.]))
    maxima = np.array([[-1., -.5]])
    assert alignment.summarize_maxima(maxima, present=np.array([True])) == (
        TermCoverage(-.75, -1., -.875, 0., 0., -.625),)
    unweighted = TermAlignment(np.eye(2), np.zeros(2))
    assert unweighted.summarize_maxima(maxima, present=np.array([True]))[0].weighted == 0.


def test_empty_query_and_empty_batch_preserve_finite_zero_coverage():
    alignment = TermAlignment(np.empty((0, 2)), np.empty(0))
    assert alignment.summarize_maxima(np.empty((3, 0)), present=np.ones(3, dtype=bool)) == (
        TermCoverage(),)*3
    assert alignment.summarize_maxima(np.empty((0, 0)), present=np.empty(0, dtype=bool)) == ()


def test_invalid_active_rows_or_misaligned_presence_cannot_become_zero_evidence():
    alignment = TermAlignment(np.eye(2), np.ones(2))
    for maxima, present in [
        (np.ones((2, 3)), np.ones(2, dtype=bool)),
        (np.ones((2, 2)), np.ones(1, dtype=bool)),
        (np.ones((2, 2)), np.ones(2)),
        (np.array([[np.nan, 1.]]), np.array([True])),
    ]:
        with pytest.raises(ValueError):
            alignment.summarize_maxima(maxima, present=present)


def test_readonly_input_arrays_are_never_modified():
    alignment = TermAlignment(np.eye(2), np.array([1., 2.]))
    maxima = np.array([[.2, .7], [-np.inf, -np.inf]], dtype=np.float32)
    present = np.array([True, False])
    before = maxima.copy()
    maxima.flags.writeable = present.flags.writeable = False
    alignment.summarize_maxima(maxima, present=present)
    assert np.array_equal(maxima, before)
