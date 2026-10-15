import numpy as np
import pytest


def test_identity_targets_keep_the_original_geometry():
    from query_transport import fit_transport

    queries = np.array([[1., 0.], [0., 1.], [.6, .8]])
    model = fit_transport(queries, queries, np.ones(3), regularization=1.)
    np.testing.assert_array_equal(model.matrix, np.eye(2))
    np.testing.assert_array_equal(model.transform(queries), queries.astype(np.float32))
    assert model.normal_equation_residual == 0.


def test_view_weights_prevent_duplicating_a_query_vote():
    from query_transport import fit_transport

    q, y = np.eye(2), np.array([[0., 1.], [1., 0.]])
    original = fit_transport(q, y, np.ones(2), regularization=1.)
    repeated = fit_transport(q[[0, 0, 1]], y[[0, 0, 1]], np.array([.5, .5, 1.]), regularization=1.)
    np.testing.assert_allclose(original.matrix, repeated.matrix, rtol=0., atol=1e-15)
    np.testing.assert_array_equal(original.transform(q), repeated.transform(q))


def test_mean_shift_uses_only_weighted_source_minus_question_offsets():
    from query_transport import fit_transport

    model = fit_transport(np.array([[1., 0.], [0., 1.]]), np.array([[0., 1.], [-1., 0.]]),
                          np.array([1., 3.]), regularization=None)
    np.testing.assert_array_equal(model.shift, [-1., -.5])
    np.testing.assert_array_equal(model.matrix, np.eye(2))


def test_transport_rejects_invalid_weights_and_zero_output():
    from query_transport import fit_transport

    q = np.eye(2)
    with pytest.raises(ValueError, match='positive'):
        fit_transport(q, q, np.array([1., -1.]), regularization=1.)
    model = fit_transport(q, -q, np.ones(2), regularization=None)
    with pytest.raises(ValueError, match='nonzero'):
        model.transform(np.ones((1, 2)))
