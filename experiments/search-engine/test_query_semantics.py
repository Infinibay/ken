"""Signed query descriptors remain numerical evidence, with stable asset replay."""
import json

import numpy as np
import pytest

from query_semantics import SemanticContrasts


def test_each_contrast_distinguishes_its_two_endpoints_in_catalog_order():
    positive = np.array([[1., 0., 0.], [0., 0., 1.]])
    negative = np.array([[0., 1., 0.], [0., 0., -1.]])
    contrasts = SemanticContrasts.from_pairs(positive, negative)
    np.testing.assert_allclose(contrasts.project([1., 0., 0.]), [2**-.5, 0.])
    np.testing.assert_allclose(contrasts.project([0., 1., 0.]), [-2**-.5, 0.])
    np.testing.assert_array_equal(contrasts.project([0., 0., 1.]), [0., 1.])
    assert contrasts.project([1., 2., 3.]).dtype == np.float64


def test_projection_handles_extreme_finite_scales_and_does_not_change_inputs():
    positive = np.array([[1e308, 0.]])
    negative = np.array([[0., 1e-320]])
    original = positive.copy()
    contrasts = SemanticContrasts.from_pairs(positive, negative)
    np.testing.assert_array_equal(positive, original)
    for scale in (1e-320, 1., 1e308):
        np.testing.assert_array_equal(contrasts.project([scale, 0.]), contrasts.project([1., 0.]))


def test_saved_axes_roundtrip_exactly_and_detach_mutable_asset_buffers():
    contrasts = SemanticContrasts.from_pairs([[1., 2., 3.]], [[-1., 2., 0.]])
    restored = SemanticContrasts(np.asarray(json.loads(json.dumps(contrasts.axes.tolist()))))
    query = np.array([4., 2., -1.])
    expected = contrasts.project(query)
    np.testing.assert_array_equal(expected, restored.project(query))
    assert not contrasts.axes.flags.writeable
    source = restored.axes.copy()
    detached = SemanticContrasts(source)
    source[:] = 0
    np.testing.assert_array_equal(detached.project(query), expected)
    query[:] = 0
    np.testing.assert_array_equal(detached.axes, contrasts.axes)


@pytest.mark.parametrize('positive,negative', [
    ([[0., 0.]], [[1., 0.]]), ([[1., 0.]], [[1., 0.]]),
    ([[np.nan, 0.]], [[1., 0.]]), ([[np.inf, 0.]], [[1., 0.]]),
    ([[1., 0.]], [[1., 0., 0.]]), ([1., 0.], [0., 1.]), ([], []),
])
def test_invalid_or_undefined_contrasts_fail(positive, negative):
    with pytest.raises(ValueError):
        SemanticContrasts.from_pairs(positive, negative)


@pytest.mark.parametrize('query', [[0., 0.], [np.nan, 0.], [np.inf, 0.], [1.], [[1., 0.]]])
def test_invalid_query_shape_or_magnitude_fails(query):
    contrasts = SemanticContrasts.from_pairs([[1., 0.]], [[0., 1.]])
    with pytest.raises(ValueError):
        contrasts.project(query)


def test_loading_nonunit_or_empty_axes_cannot_relabel_an_unregistered_transform():
    for axes in (np.zeros((2, 3)), np.ones((2, 3)), np.empty((0, 3)), np.array([1., 0.])):
        with pytest.raises(ValueError):
            SemanticContrasts(axes)
