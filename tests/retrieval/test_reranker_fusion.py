import pytest

from ken.retrieval.reranker_fusion import fused_reranker_order


def test_fusion_combines_existing_position_with_reranker_position():
    # Neural order is [2, 0, 1, 3]; equal RRF60 weights prefer the consensus 0.
    assert fused_reranker_order([8., 4., 12., -1.]) == [0, 2, 1, 3]


def test_equal_scores_preserve_existing_order_and_identity():
    assert fused_reranker_order([2., 2., 2.]) == [0, 1, 2]
    assert fused_reranker_order([]) == []
    assert fused_reranker_order([3.]) == [0]


def test_equal_fusion_tie_preserves_existing_order():
    assert fused_reranker_order([0., 10.]) == [0, 1]


def test_weights_zero_and_one_select_the_corresponding_ranking():
    assert fused_reranker_order([1., 2., 3.], neural_weight=0.) == [0, 1, 2]
    assert fused_reranker_order([1., 2., 3.], neural_weight=1.) == [2, 1, 0]


@pytest.mark.parametrize('scores', [[float('nan')], [float('inf')], [-float('inf')]])
def test_fusion_refuses_nonfinite_model_scores(scores):
    with pytest.raises(ValueError, match='finite'):
        fused_reranker_order(scores)


@pytest.mark.parametrize('weight,offset', [(-.1, 60.), (1.1, 60.), (float('nan'), 60.),
                                         (.5, -1.), (.5, float('inf'))])
def test_fusion_refuses_invalid_configuration(weight, offset):
    with pytest.raises(ValueError):
        fused_reranker_order([1.], neural_weight=weight, rank_offset=offset)
