import numpy as np
import pytest

def test_pairwise_training_excludes_complete_heldout_and_missing_positive_groups():
    from linear_decision_training import pairwise_examples
    x=np.array([[4.],[1.],[0.],[5.],[2.],[7.],[6.]])
    y=np.array([1,0,0,1,0,0,0]);q=np.array(['a','a','a','b','b','c','c']);repos=np.array(['train','train','train','held','held','train','train'])
    batch=pairwise_examples(x,y,q,repos,np.arange(7.),held_out='held')
    assert batch['queries']==['a']
    assert batch['differences'].tolist()==[[3.],[4.]]
    assert batch['offsets'].tolist()==[-1.,-2.]
    assert batch['weights'].tolist()==[.5,.5]


def test_pairwise_examples_give_each_query_equal_total_weight():
    from linear_decision_training import pairwise_examples
    batch=pairwise_examples(np.arange(5.).reshape(-1,1),np.array([1,0,0,1,0]),np.array(['a','a','a','b','b']),np.array(['train']*5),np.zeros(5),held_out=None)
    assert batch['weights'].tolist()==[.25,.25,.5]
    assert batch['queries']==['a','b']


def test_logistic_loss_gradient_matches_finite_difference_and_stays_finite():
    from linear_decision_training import logistic_loss
    x=np.array([[1.,2.],[-2.,1.]]);offset=np.array([.4,-.7]);weight=np.array([.3,.7]);theta=np.array([.2,-.1])
    loss,grad=logistic_loss(theta,x,offset,weight)
    numerical=[]
    for i in range(2):
        delta=np.eye(2)[i]*1e-6
        numerical.append((logistic_loss(theta+delta,x,offset,weight)[0]-logistic_loss(theta-delta,x,offset,weight)[0])/2e-6)
    assert grad==pytest.approx(numerical,abs=1e-7)
    assert np.isfinite(logistic_loss(theta,x,np.array([1e4,-1e4]),weight)[0])
    assert loss>0


def test_mixed_repository_query_is_not_silently_partially_trained():
    from linear_decision_training import pairwise_examples
    with pytest.raises(ValueError,match='repository'):
        pairwise_examples(np.array([[1.],[0.]]),np.array([1,0]),np.array(['same','same']),np.array(['train','held']),np.zeros(2),held_out='held')


def test_regularization_is_scaled_in_both_loss_and_gradient():
    from linear_decision_training import logistic_loss
    theta=np.array([2.,-1.]);x=np.zeros((1,2));offset=np.zeros(1);weight=np.ones(1)
    loss,gradient=logistic_loss(theta,x,offset,weight,regularization=.01)
    assert loss==pytest.approx(np.log(2.)+.025)
    assert gradient==pytest.approx([.02,-.01])
