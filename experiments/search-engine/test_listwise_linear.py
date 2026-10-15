"""A small convex ranker must preserve query weighting and repository exclusion."""
import numpy as np
import pytest
from listwise_linear import LinearListRanker, ListwiseFitError, RankGroup, fit_listwise, listwise_objective, prepare_listwise


def test_objective_gradient_matches_independent_central_differences():
    x=np.array([[2.,0.],[0.,1.],[-1.,1.],[1.,1.],[0.,-1.]])
    targets=np.array([.5,0.,.5,1.,0.]);starts=np.array([0,3]);w=np.array([.2,-.3])
    value,gradient=listwise_objective(w,x,targets,starts)
    for i in range(2):
        delta=np.eye(2)[i]*1e-6
        numeric=(listwise_objective(w+delta,x,targets,starts)[0]-listwise_objective(w-delta,x,targets,starts)[0])/2e-6
        assert gradient[i]==pytest.approx(numeric,abs=1e-8)
    assert np.isfinite(value)


def test_query_constant_score_translation_does_not_change_loss_or_gradient():
    x=np.array([[2.,0.],[0.,1.],[1.,1.],[0.,-1.]])
    shifted=x+np.repeat([[1000.,-500.],[-700.,900.]],2,axis=0)
    args=(np.array([.2,-.3]),np.array([1.,0.,1.,0.]),np.array([0,2]))
    a=listwise_objective(args[0],x,args[1],args[2]);b=listwise_objective(args[0],shifted,args[1],args[2])
    assert a[0]==pytest.approx(b[0],abs=1e-10)
    np.testing.assert_allclose(a[1],b[1],atol=1e-10,rtol=0)


def test_each_query_has_equal_weight_even_with_unequal_candidate_counts():
    x=np.array([[1.],[0.],[0.],[1.],[0.]])
    loss,gradient=listwise_objective(np.zeros(1),x,np.array([1.,0.,0.,1.,0.]),np.array([0,3]))
    assert loss==pytest.approx(np.log(3)+np.log(2))
    assert gradient[0]==pytest.approx(-2/3-1/2)


def groups():
    return [RankGroup('a','one',np.array([[2.,5.],[0.,5.]]),np.array([1,0])),
            RankGroup('b','two',np.array([[3.,5.],[1.,5.],[-1.,5.]]),np.array([1,0,0]))]


def test_fit_ignores_all_held_features_and_labels_and_roundtrips_exactly():
    held=RankGroup('held','held',np.array([[1e50,1e50],[0.,0.]]),np.array([0,1]))
    a,info=fit_listwise([*groups(),held],excluded_repositories={'held'})
    altered=RankGroup('held','held',np.full((2,2),np.nan),np.array([5,7]))
    b,_=fit_listwise([*groups(),altered],excluded_repositories={'held'})
    assert info['training_repositories']==['a','b'] and info['training_queries']==2
    assert info['max_abs_gradient']<=1e-4
    np.testing.assert_array_equal(a.weights,b.weights)
    np.testing.assert_array_equal(a.means,b.means)
    np.testing.assert_array_equal(a.scales,b.scales)
    assert a.scales[1]==1.
    x=groups()[0].values
    assert a.score(x)[0]>a.score(x)[1]
    restored=LinearListRanker.from_dict(a.to_dict())
    np.testing.assert_array_equal(a.score(x),restored.score(x))
    assert not a.weights.flags.writeable and not a.means.flags.writeable and not a.scales.flags.writeable


def test_normalizer_weights_queries_equally_not_candidate_density():
    model,_=fit_listwise(groups(),excluded_repositories=set())
    assert model.means[0]==pytest.approx(1.)
    # Query1 variance1; query2 variance8/3, each weight1/2.
    assert model.scales[0]==pytest.approx(np.sqrt(11/6))


@pytest.mark.parametrize('bad', [np.array([[np.nan,0.]]),np.array([[1.]]),np.array([[1j,0.]])])
def test_invalid_score_inputs_fail(bad):
    model,_=fit_listwise(groups(),excluded_repositories=set())
    with pytest.raises(ValueError):model.score(bad)


def test_invalid_training_groups_are_explicit_failures():
    for values,labels in (([[1.],[0.]],[0,0]),([[1.],[0.]],[1,1]),([[np.nan],[0.]],[1,0]),([[1.],[0.]],[1,2])):
        with pytest.raises(ValueError):fit_listwise([RankGroup('a','q',np.array(values),np.array(labels))],excluded_repositories=set())


def test_optimizer_failure_retains_its_trace_without_exporting_a_head(monkeypatch):
    from scipy.optimize import OptimizeResult
    def unsuccessful(fun,x0,**kwargs):
        fun(x0)
        return OptimizeResult(x=x0,success=False,message='iteration budget reached',nit=1,nfev=1)
    monkeypatch.setattr('scipy.optimize.minimize',unsuccessful)
    with pytest.raises(ListwiseFitError) as captured:
        fit_listwise(groups(),excluded_repositories=set())
    assert captured.value.diagnostics['training_queries']==2
    assert captured.value.diagnostics['trace']
    assert captured.value.diagnostics['message']=='iteration budget reached'


def test_prepared_training_can_be_audited_without_fitting_and_detaches_inputs():
    source=groups()
    held=RankGroup('held','held',np.full((2,2),np.nan),np.array([5,7]))
    training=prepare_listwise([*source,held],excluded_repositories={'held'})
    assert training.repositories==('a','b') and training.query_ids==('one','two')
    np.testing.assert_array_equal(training.starts,[0,2])
    np.testing.assert_allclose(np.add.reduceat(training.targets,training.starts),1.,rtol=0,atol=1e-15)
    before=training.values.copy()
    source[0].values[0,0]=-999
    np.testing.assert_array_equal(training.values,before)
    assert not training.values.flags.writeable and not training.targets.flags.writeable


def test_finite_features_cannot_produce_an_infinite_prepared_normalizer():
    with pytest.raises(ValueError,match='normalization'):
        prepare_listwise([RankGroup('a','q',np.array([[1e200],[-1e200]]),np.array([1,0]))],
                         excluded_repositories=set())


def test_valid_unsigned_group_offsets_match_signed_offsets():
    args=(np.array([.2]),np.array([[1.],[0.],[2.],[0.]]),np.array([1.,0.,1.,0.]))
    signed=listwise_objective(*args,np.array([0,2],dtype=np.int64))
    unsigned=listwise_objective(*args,np.array([0,2],dtype=np.uint64))
    assert signed[0]==unsigned[0]
    np.testing.assert_array_equal(signed[1],unsigned[1])
