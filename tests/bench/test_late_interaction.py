import numpy as np
import pytest

from ken.bench.late_interaction import DocumentVectors, maxsim


def test_maxsim_keeps_negative_similarity_and_counts_query_tokens_once():
    query = np.array([[1., 0.], [0., 1.]], dtype=np.float32)
    document = np.array([[-1., 0.], [-.6, -.8]], dtype=np.float32)
    assert maxsim(query, document) == pytest.approx(-.6)
    assert maxsim(query, np.repeat(document, 10, axis=0)) == pytest.approx(-.6)
    with pytest.raises(ValueError, match='finite|empty|dimension'):
        maxsim(query, np.empty((0, 2)))


def test_document_cache_is_bound_to_content_and_encoder_revision(tmp_path):
    calls = []
    def encode(texts):
        calls.append(texts)
        return [np.array([[1., 0.], [0., 1.]], dtype=np.float32) for t in texts]
    path = tmp_path/'vectors.db'
    with DocumentVectors(path, 'revision-a', encode) as cache:
        first = cache.get_many(['body', 'body', 'other'])
        assert calls == [['body', 'other']]
        assert np.array_equal(first[0], first[1])
        cache.get_many(['other', 'edited body'])
        assert calls[-1] == ['edited body']
    with DocumentVectors(path, 'revision-a', encode) as cache:
        cache.get_many(['body'])
        assert len(calls) == 2
    with DocumentVectors(path, 'revision-b', encode) as cache:
        cache.get_many(['body'])
        assert len(calls) == 3


def test_invalid_encoder_batch_does_not_publish_partial_documents(tmp_path):
    def bad(texts):
        return [np.array([[1., 0.]]), np.array([[float('nan'), 0.]])]
    with DocumentVectors(tmp_path/'v.db', 'revision', bad) as cache:
        with pytest.raises(ValueError, match='finite'):
            cache.get_many(['valid', 'invalid'])
        assert cache.count() == 0


def test_colbert_tokens_use_separate_prefix_and_mask_expansion():
    import torch
    from ken.bench.late_interaction import prepare_features
    class Tokenizer:
        def __call__(self, texts, **kwargs):
            assert texts == ['a query']
            assert kwargs == {'padding': 'max_length', 'truncation': True,
                              'max_length': 4, 'return_tensors': 'pt'}
            return {'input_ids': torch.tensor([[101, 7, 102, 103]]),
                    'attention_mask': torch.tensor([[1, 1, 1, 0]]),
                    'token_type_ids': torch.tensor([[0, 0, 0, 0]])}
    features = prepare_features(Tokenizer(), [' a query '], prefix_id=30522, length=5, query=True)
    assert features['input_ids'].tolist() == [[101, 30522, 7, 102, 103]]
    assert features['attention_mask'].tolist() == [[1, 1, 1, 1, 0]]
    assert features['token_type_ids'].tolist() == [[0, 0, 0, 0, 0]]
