"""Check the token interaction math through its compact public representation."""
import numpy as np
import pytest

from late_interaction import compact_tokens, interaction_statistics, project_tokens


def test_projection_is_shared_deterministic_and_normalized():
    raw = np.random.default_rng(5).normal(size=(9, 768)).astype(np.float32)
    first = project_tokens(raw)
    second = project_tokens(raw.copy())
    assert first.shape == (9, 128)
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first, axis=1), 1, atol=1e-6)


def test_quantized_bag_preserves_simple_exact_and_missing_matches():
    source = np.array([[1., 0.], [0., 1.]], dtype=np.float32)
    query = np.array([[1., 0.], [0., 1.], [-1., 0.]], dtype=np.float32)
    packed = compact_tokens(source)
    assert packed.dtype == np.int8
    actual = interaction_statistics(query, packed, np.array([1., 2., 3.]))
    assert actual == pytest.approx((2/3, 0., .5, .5, 2/3, 2/3))


def test_empty_implementation_has_zero_statistics_without_invented_match():
    query = np.array([[1., 0.]], dtype=np.float32)
    assert interaction_statistics(query, np.empty((0, 2), dtype=np.int8),
                                  np.ones(1)) == (0.,)*6
    assert compact_tokens(np.empty((0, 2), dtype=np.float32)).shape == (0, 2)


def test_quantization_and_matching_do_not_mutate_inputs():
    source = np.random.default_rng(4).normal(size=(7, 128)).astype(np.float32)
    source /= np.linalg.norm(source, axis=1, keepdims=True)
    before = source.copy()
    packed = compact_tokens(source)
    query = source[:3].copy()
    statistics = interaction_statistics(query, packed, np.array([1., 2., 3.]))
    assert np.array_equal(source, before)
    assert np.array_equal(query, before[:3])
    assert statistics[0] > .999


def test_invalid_geometry_cannot_silently_become_missing_evidence():
    query = np.array([[1., 0.]], dtype=np.float32)
    with pytest.raises(ValueError):
        project_tokens(np.zeros((1, 768), dtype=np.float32))
    with pytest.raises(ValueError):
        compact_tokens(np.array([[np.nan, 0.]], dtype=np.float32))
    with pytest.raises(ValueError):
        interaction_statistics(query, np.zeros((1, 2), dtype=np.int8), np.ones(1))
    with pytest.raises(ValueError):
        interaction_statistics(query, np.ones((1, 3), dtype=np.int8), np.ones(1))
    with pytest.raises(ValueError):
        interaction_statistics(query, np.ones((1, 2), dtype=np.int8), np.zeros(1))


@pytest.mark.parametrize('magnitude,dtype', [(1e30, np.float32), (1e300, np.float64)])
def test_projection_rejects_finite_inputs_outside_safe_float32_norm_range(magnitude, dtype):
    with pytest.raises(ValueError):
        project_tokens(np.full((1, 768), magnitude, dtype=dtype))
