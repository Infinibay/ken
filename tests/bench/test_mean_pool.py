import numpy as np
import pytest

from ken.bench.mean_pool import masked_mean


def test_mean_pool_masks_padding_then_normalizes_each_document():
    hidden = np.array([[[3.,0.],[0.,4.],[999.,999.]],[[1.,0.],[1.,0.],[1.,0.]]],dtype=np.float32)
    mask = np.array([[1,1,0],[1,1,1]])
    result = masked_mean(hidden,mask)
    np.testing.assert_allclose(result,[[.6,.8],[1.,0.]],atol=1e-6)
    assert result.dtype == np.float32
    with pytest.raises(ValueError,match='nonempty|mask|finite'):
        masked_mean(hidden,np.zeros_like(mask))


def test_token_count_does_not_hide_overflow_and_restores_encoder_policy():
    from threading import RLock
    from ken.bench.mean_pool import full_token_count
    from tests.bench.test_pair_relevance import tokenizer
    t = tokenizer()
    t.enable_truncation(max_length=8)
    assert full_token_count(t,'query '*40,lock=RLock()) == 40
    assert t.truncation['max_length'] == 8
    assert len(t.encode('query '*40).ids) == 8
