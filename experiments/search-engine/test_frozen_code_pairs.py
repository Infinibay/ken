"""Pairing keeps the full request and bounds only the source text."""
from types import SimpleNamespace

import numpy as np
import pytest
from tokenizers import Tokenizer, models, pre_tokenizers, processors

from frozen_code_pairs import FrozenCodePairs


class Session:
    def __init__(self, vector=None, providers=None):
        self.vector = np.array([[3., 4.]], dtype=np.float32) if vector is None else vector
        self.inputs = []
        self.providers = ['CPUExecutionProvider'] if providers is None else providers

    def get_providers(self):
        return self.providers

    def get_inputs(self):
        return [SimpleNamespace(name=name) for name in ('input_ids', 'attention_mask')]

    def run(self, outputs, inputs):
        assert outputs == ['sentence_embedding']
        self.inputs.append({name: value.copy() for name, value in inputs.items()})
        return [self.vector]


def tokenizer():
    vocab = {token: index for index, token in enumerate(('[UNK]', '[CLS]', '[SEP]', 'Q', 'find', 'red', 'x'))}
    tok = Tokenizer(models.WordLevel(vocab, unk_token='[UNK]'))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(single='[CLS] $A [SEP]',
        pair='[CLS] $A [SEP] $B:1 [SEP]:1', special_tokens=[('[CLS]', 1), ('[SEP]', 2)])
    tok.enable_padding(length=40)
    tok.enable_truncation(max_length=24)
    return tok


def test_public_pair_encoding_preserves_query_bounds_document_and_does_not_mutate_tokenizer():
    original, session = tokenizer(), Session()
    before = original.to_str()
    pairs = FrozenCodePairs(session, original, query_prefix='Q ', dimension=2, max_tokens=9)
    vectors = pairs.encode('find red', ['x '*100, 'x'])
    assert original.to_str() == before
    assert session.inputs[0]['input_ids'].tolist() == [[1, 3, 4, 5, 2, 6, 6, 6, 2]]
    assert session.inputs[1]['input_ids'].tolist() == [[1, 3, 4, 5, 2, 6, 2]]
    np.testing.assert_array_equal(session.inputs[0]['attention_mask'], np.ones((1, 9), dtype=np.int64))
    np.testing.assert_allclose(vectors, [[.6, .8], [.6, .8]], rtol=0., atol=3e-8)
    assert vectors.dtype == np.float32
    assert pairs.encode('find red', []).shape == (0, 2)


def test_overlong_query_fails_instead_of_truncating_it():
    pairs = FrozenCodePairs(Session(), tokenizer(), query_prefix='Q ', dimension=2, max_tokens=9)
    with pytest.raises(Exception, match='(?i)truncat|too short'):
        pairs.encode('find '*20, ['x '*100])


@pytest.mark.parametrize('vector', [
    np.zeros((1, 2), dtype=np.float32),
    np.array([[np.nan, 1.]], dtype=np.float32),
    np.array([[np.inf, 1.]], dtype=np.float32),
    np.ones((2,), dtype=np.float32),
    np.ones((1, 3), dtype=np.float32),
    np.ones((1, 2), dtype=np.int64),
])
def test_invalid_joint_vectors_are_rejected(vector):
    pairs = FrozenCodePairs(Session(vector), tokenizer(), query_prefix='Q ', dimension=2)
    with pytest.raises(ValueError):
        pairs.encode('find red', ['x'])


@pytest.mark.parametrize('value', [np.finfo(np.float32).max, np.nextafter(np.float32(0), np.float32(1))])
def test_finite_extreme_vectors_normalize_without_overflow_or_underflow(value):
    pairs = FrozenCodePairs(Session(np.array([[value, value]], dtype=np.float32)), tokenizer(), query_prefix='Q ', dimension=2)
    np.testing.assert_allclose(pairs.encode('find red', ['x']), [[2**-.5, 2**-.5]], atol=3e-8, rtol=0.)


def test_provider_and_budget_contract():
    with pytest.raises(ValueError, match='CPU'):
        FrozenCodePairs(Session(providers=['CUDAExecutionProvider']), tokenizer(), query_prefix='Q ', dimension=2)
    for values in ({'dimension': 0}, {'max_tokens': 0}, {'dimension': True}, {'max_tokens': 1.5}):
        with pytest.raises(ValueError):
            FrozenCodePairs(Session(), tokenizer(), query_prefix='Q ', **{'dimension': 2, **values})
