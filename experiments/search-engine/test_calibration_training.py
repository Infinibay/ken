import numpy as np
import calibration_training as training

def test_holds_repository_out_and_keeps_every_negative_from_trainable_groups():
    q=np.array(['a','a','b','b','c','c','d','d']);repo=np.array(['x','x','x','x','y','y','x','x']);y=np.array([1,0,0,0,1,0,1,1]);kind=np.array(['class','class','symbol','symbol','symbol','symbol','file','file'])
    mask,weights=training.training_selection(q,repo,kind,y,held_out='y')
    np.testing.assert_array_equal(mask,[True,True,False,False,False,False,False,False])
    assert weights.tolist()==[1.,1.]

def test_balances_query_weight_by_kind_not_candidate_count():
    q=np.array(['a','a','a','b','b','c','c']);repo=np.array(['x']*7);y=np.array([1,0,0,1,0,1,0]);kind=np.array(['class']*3+['symbol']*4)
    mask,w=training.training_selection(q,repo,kind,y,held_out=None)
    assert mask.all()
    # Two symbol queries share the same total weight as one class query.
    assert np.isclose(w[q=='a'].sum(),w[q!='a'].sum())
    assert np.isclose(w[q=='b'].sum(),w[q=='c'].sum())
