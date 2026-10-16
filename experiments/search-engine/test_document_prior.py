from types import SimpleNamespace
import numpy as np
import pytest

def test_control_removes_only_question_tokens_and_padding():
    from document_prior import control_tokens
    encoded=SimpleNamespace(ids=[101,3,4,102,8,9,102,0],sequence_ids=[None,0,0,None,1,1,None,None],attention_mask=[1,1,1,1,1,1,1,0])
    assert control_tokens(encoded)==[101,102,8,9,102]


def test_control_preserves_an_empty_question_and_the_visible_document_prefix():
    from document_prior import control_tokens
    e=SimpleNamespace(ids=[101,102,77,88,102],sequence_ids=[None,None,1,1,None],attention_mask=[1]*5)
    assert control_tokens(e)==e.ids


def test_control_rejects_encodings_without_document_provenance():
    from document_prior import control_tokens
    e=SimpleNamespace(ids=[101,4,102],sequence_ids=[None,0,None],attention_mask=[1]*3)
    with pytest.raises(ValueError,match='document'):control_tokens(e)


def test_document_prior_difference_is_finite_and_candidate_aligned():
    from document_prior import conditional_scores
    assert conditional_scores([9.,8.],[8.,6.]).tolist()==[1.,2.]
    with pytest.raises(ValueError):conditional_scores([1.],[2.,3.])
    with pytest.raises(ValueError):conditional_scores([float('inf')],[0.])
    with pytest.raises(ValueError):conditional_scores([1e308],[-1e308])
