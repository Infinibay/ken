import numpy as np
import pytest
from evidence_ranks import reciprocal_evidence_rank


def test_tied_scores_share_the_average_descending_rank():
    np.testing.assert_allclose(reciprocal_evidence_rank(np.array([1.,3.,3.,0.])),[1/3,2/3,2/3,1/4],rtol=0,atol=0)


def test_evidence_rank_is_permutation_equivariant_including_ties():
    values=np.array([1.,3.,3.,0.,0.,2.]);permutation=np.array([4,2,0,3,5,1])
    np.testing.assert_array_equal(reciprocal_evidence_rank(values[permutation]),reciprocal_evidence_rank(values)[permutation])


def test_a_constant_channel_is_neutral_instead_of_voting_for_proposal_order():
    for value in(0.,7.,-3.):
        np.testing.assert_array_equal(reciprocal_evidence_rank(np.full(5,value)),np.zeros(5))
    np.testing.assert_array_equal(reciprocal_evidence_rank(np.array([8.])),[0.])
    assert reciprocal_evidence_rank(np.array([])).shape==(0,)


def test_integer_extremes_preserve_distinctions_without_negation_or_float_coercion():
    for dtype in(np.int64,np.uint64):
        end=np.iinfo(dtype).max
        np.testing.assert_array_equal(reciprocal_evidence_rank(np.array([end-1,end],dtype=dtype)),[.5,1.])
    start=np.iinfo(np.int64).min
    np.testing.assert_array_equal(reciprocal_evidence_rank(np.array([start,start+1],dtype=np.int64)),[.5,1.])


@pytest.mark.parametrize('bad',[np.array([np.nan]),np.array([np.inf]),np.array([1j]),np.array([True]),np.zeros((1,1))])
def test_invalid_score_vectors_fail(bad):
    with pytest.raises(ValueError):reciprocal_evidence_rank(bad)
