import pytest


def test_balanced_rank_tie_keeps_native_order():
    from verifiable_precision import precision_orders
    orders=precision_orders([1.0,2.0])
    assert orders['fp32_raw']==[1,0]
    assert orders['fp32_rrf50']==[0,1]


def test_reordering_keeps_the_same_ten_candidates_and_stable_equal_scores():
    from verifiable_precision import precision_orders
    orders=precision_orders([1.0]*10)
    assert all(order==list(range(10)) for order in orders.values())
    reverse=precision_orders(list(range(10)))
    assert reverse['fp32_raw']==list(reversed(range(10)))
    assert all(sorted(order)==list(range(10)) for order in reverse.values())


def test_unique_exact_lookup_bypasses_neural_order():
    from verifiable_precision import precision_orders
    assert all(order==[0,1,2] for order in precision_orders([1.,3.,2.],exact=True).values())


def test_nonfinite_scores_are_rejected():
    from verifiable_precision import precision_orders
    with pytest.raises(ValueError,match='finite'):
        precision_orders([1.,float('nan')])


def test_scoring_a_prefix_preserves_all_ten_retrieved_candidates():
    from verifiable_precision import precision_orders
    orders=precision_orders([1.,3.,2.],total=10)
    assert orders['fp32_raw']==[1,2,0,3,4,5,6,7,8,9]
    assert all(sorted(order)==list(range(10)) for order in orders.values())
    assert all(order[3:]==list(range(3,10)) for order in orders.values())


def test_exact_prefix_and_invalid_prefix_boundaries():
    from verifiable_precision import precision_orders
    assert all(order==list(range(10)) for order in precision_orders([1.,3.,2.],total=10,exact=True).values())
    with pytest.raises(ValueError,match='prefix'):
        precision_orders([1.,3.,2.],total=2)
