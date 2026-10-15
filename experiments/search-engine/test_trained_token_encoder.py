"""The small trained model gets explicit BERT markers and faithful masks."""
from types import SimpleNamespace

import numpy as np
import pytest


def encoding():
    return SimpleNamespace(ids=[101, 104, 105, 102], attention_mask=[1]*4,
        type_ids=[0]*4, offsets=[(0, 0), (0, 5), (5, 6), (0, 0)])


def test_marker_is_inserted_after_cls_without_replacing_a_real_token_or_offset():
    from trained_token_encoder import bert_marker_input

    raw = encoding()
    inputs, ids, offsets = bert_marker_input(raw, marker=2, max_length=5)
    np.testing.assert_array_equal(ids, [101, 2, 104, 105, 102])
    assert offsets == ((0, 0), (0, 0), (0, 5), (5, 6), (0, 0))
    assert set(inputs) == {'input_ids', 'attention_mask', 'token_type_ids'}
    assert all(value.dtype == np.int64 and value.shape == (1, 5) for value in inputs.values())
    assert raw.ids == [101, 104, 105, 102]
    assert raw.offsets == [(0, 0), (0, 5), (5, 6), (0, 0)]


def test_input_budget_is_checked_after_marker_and_truncation_is_never_implicit():
    from trained_token_encoder import bert_marker_input

    with pytest.raises(ValueError):
        bert_marker_input(encoding(), marker=2, max_length=4)
    raw = encoding()
    raw.attention_mask.pop()
    with pytest.raises(ValueError):
        bert_marker_input(raw, marker=1, max_length=128)
    with pytest.raises(ValueError):
        bert_marker_input(encoding(), marker=103, max_length=128)


def test_query_and_document_masks_follow_distinct_registered_punctuation_policy():
    from trained_token_encoder import retained_tokens

    ids = np.array([101, 2, 104, 105, 102, 0])
    np.testing.assert_array_equal(retained_tokens(ids, {105}, is_query=False),
                                  [True, True, True, False, True, False])
    np.testing.assert_array_equal(retained_tokens(ids, {105}, is_query=True),
                                  [True, True, True, True, True, False])


def test_normalized_head_output_is_validated_without_silent_extra_normalization():
    from trained_token_encoder import validated_token_vectors

    values = np.eye(3, 96, dtype=np.float32)
    output = values[None, :]
    before = output.copy()
    np.testing.assert_array_equal(validated_token_vectors(output, length=3), values)
    np.testing.assert_array_equal(output, before)
    for bad in [np.ones((1, 3, 96), dtype=np.float32), np.zeros((1, 3, 96)),
                np.full((1, 3, 96), np.nan), np.ones((1, 3, 32))]:
        with pytest.raises(ValueError):
            validated_token_vectors(bad, length=3)


def test_token_masks_require_a_nonnegative_integer_id_vector():
    from trained_token_encoder import retained_tokens

    for ids in [np.ones((2, 2), dtype=int), np.array([-1, 1]), np.array([1., 2.])]:
        with pytest.raises(ValueError):
            retained_tokens(ids, {105}, is_query=False)
