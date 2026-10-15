import numpy as np
import pytest
from choice_loss import QueryChoiceLoss


def test_choice_derivatives_match_independent_score_finite_differences():
    loss=QueryChoiceLoss(np.array([1.,0.,0.,.5,.5]),np.array([0,3],dtype=np.uint64))
    scores=np.array([.4,-.2,.1,.8,-.3]);gradient,diagonal=loss.derivatives(scores)
    for i in range(len(scores)):
        d=np.eye(len(scores))[i]*1e-5
        numeric=(loss.value(scores+d)-loss.value(scores-d))/2e-5
        second=(loss.derivatives(scores+d)[0][i]-loss.derivatives(scores-d)[0][i])/2e-5
        assert gradient[i]==pytest.approx(numeric,abs=1e-9)
        assert diagonal[i]==pytest.approx(second,abs=1e-9)
    np.testing.assert_allclose(np.add.reduceat(gradient,[0,3]),0.,rtol=0,atol=1e-15)


def test_query_weight_and_translation_are_independent_of_candidate_density():
    loss=QueryChoiceLoss(np.array([1.,0.,0.,1.,0.]),np.array([0,3]))
    scores=np.zeros(5);shifted=np.array([1000.,1000.,1000.,-800.,-800.])
    assert loss.value(scores)==pytest.approx(np.log(3)+np.log(2))
    assert loss.value(scores)==loss.value(shifted)
    for a,b in zip(loss.derivatives(scores),loss.derivatives(shifted),strict=True):
        np.testing.assert_array_equal(a,b)


def test_targets_are_detached_and_stable_softmax_handles_large_finite_margins():
    targets=np.array([1.,0.]);starts=np.array([0]);loss=QueryChoiceLoss(targets,starts)
    targets[:]=0;starts[:]=1
    assert loss.value(np.array([1000.,-1000.]))==0
    gradient,diagonal=loss.derivatives(np.array([1000.,-1000.]))
    np.testing.assert_array_equal(gradient,[0.,0.]);np.testing.assert_array_equal(diagonal,[0.,0.])
    assert not loss.targets.flags.writeable and not loss.starts.flags.writeable


@pytest.mark.parametrize('targets,starts', [([1.,0.],[1]),([1.,0.],[0,0]),([1.,0.],[0,2]),([1.,0.],[0.]),([.2,.2],[0]),([1.,np.nan],[0]),([1.,-1.],[0])])
def test_invalid_query_distributions_fail(targets,starts):
    with pytest.raises(ValueError):QueryChoiceLoss(np.array(targets),np.array(starts))


@pytest.mark.parametrize('scores', [[np.nan,0.],[1.],[1j,0.],[True,False]])
def test_invalid_predictions_fail(scores):
    loss=QueryChoiceLoss(np.array([1.,0.]),np.array([0]))
    with pytest.raises(ValueError):loss.derivatives(np.array(scores))
