import numpy as np
import pytest


def test_zero_residual_is_the_original_unit_query():
    from query_adapter import QueryAdapter
    query = np.array([[3., 4.]], dtype=np.float32)
    model = QueryAdapter(np.zeros((2, 2), np.float32))
    np.testing.assert_array_equal(model.transform(query), np.array([[.6, .8]], np.float32))


def test_bottleneck_preserves_joint_order_and_unit_norm():
    from query_adapter import QueryAdapter
    query = np.array([[1., 0.], [0., 1.]], dtype=np.float32)
    down = np.array([[1., -1.]], np.float32)
    up = np.array([[0.], [1.]], np.float32)
    result = QueryAdapter(down, up).transform(query)
    expected = query+np.tanh(query@down.T)@up.T
    expected /= np.linalg.norm(expected, axis=1, keepdims=True)
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_allclose(np.linalg.norm(result, axis=1), 1.)


def test_adapter_copies_immutable_weights_and_fingerprints_both_matrices():
    from query_adapter import QueryAdapter
    weights = np.zeros((2, 2), np.float32)
    model = QueryAdapter(weights)
    fingerprint = model.fingerprint
    weights[0, 0] = 1.
    assert model.fingerprint == fingerprint
    assert QueryAdapter(weights).fingerprint != fingerprint
    with pytest.raises(ValueError):
        model.down[0, 0] = 1.


@pytest.mark.parametrize(('down', 'up'), [(np.zeros((2, 3)), None), (np.zeros((1, 2)), np.zeros((3, 1))), (np.full((2, 2), np.nan), None)])
def test_adapter_rejects_incompatible_or_nonfinite_weights(down, up):
    from query_adapter import QueryAdapter
    with pytest.raises(ValueError):
        QueryAdapter(down, up)


def test_adapter_rejects_zero_and_nonfinite_query_results():
    from query_adapter import QueryAdapter
    model = QueryAdapter(-np.eye(2, dtype=np.float32))
    with pytest.raises(ValueError, match='nonzero'):
        model.transform(np.array([[1., 0.]], np.float32))
