import hashlib

import numpy as np
import pytest

from ken.retrieval.description import describe_owner
from ken.retrieval.model import Candidate, EntityKey, Passage, SearchRequest, Span


class Encoder:
    def embed_passages(self, texts):
        result = []
        for text in texts:
            vector = np.frombuffer(hashlib.sha256(text.encode()).digest()[:16], dtype=np.uint8).astype(np.float32)-128
            result.append(vector / max(1e-9, np.linalg.norm(vector)))
        return result

    def embed_query(self, text):
        return self.embed_passages([text])[0]


def test_features_use_all_owned_source_and_name_every_column_once():
    from ken.retrieval.evidence_features import evidence_features

    entity = EntityKey('store.py', 'function', 'store')
    fields = {'identity': 'function store', 'signature': 'def store():', 'documentation': 'Persistence.',
              'path': 'store.py', 'body': 'def store():'}
    first = Passage(entity, Span(1, 1), fields, 'hash', Span(1, 3), implementation_start_line=2)
    rest = Passage(entity, Span(2, 3), {**fields, 'body': '    persist(durable, cookie)\n    return cookie'},
                   'hash', Span(1, 3), implementation_start_line=2)
    candidate = Candidate(entity, [first], {'rrf': .1})
    description = describe_owner([first, rest])
    features = evidence_features(SearchRequest('persist durable cookie'), [candidate],
        {entity: description}, encoder=Encoder(), stem_words=lambda words: words)
    assert len(features.names) == len(set(features.names))
    assert features.values.shape == (1, len(features.names))
    assert np.isfinite(features.values).all()
    assert features.values[0, features.names.index('expanded_implementation_exact')] == 1.
    assert features.values[0, features.names.index('rrf_rank')] == 1.
    assert features.values[0, features.names.index('role_match')] == 1.


def test_empty_pool_has_a_stable_feature_schema_without_loading_an_encoder():
    from ken.retrieval.evidence_features import evidence_features

    class Forbidden:
        def embed_passages(self, texts):
            raise AssertionError('empty pool must not encode')
        embed_query = embed_passages

    features = evidence_features(SearchRequest('something'), [], {},
        encoder=Forbidden(), stem_words=lambda words: words)
    assert features.values.shape == (0, len(features.names))


def test_source_alignment_bounds_vector_batches_without_dropping_late_terms(monkeypatch):
    import ken.retrieval.evidence_features as module

    class LimitedEncoder(Encoder):
        def embed_passages(self, texts):
            assert len(texts) <= 8, 'alignment must stream the vocabulary'
            return super().embed_passages(texts)

    monkeypatch.setattr(module, '_TERM_BLOCK_SIZE', 8, raising=False)
    terms = ['source'+chr(97+i//26)+chr(97+i%26) for i in range(64)]
    documents = [{'body': terms, 'all': terms}]
    query = terms[-1]
    rows = module._coverage(query, documents, ('body','all'), encoder=LimitedEncoder())
    assert rows[0]['body_exact'] == 1.
    assert rows[0]['body_mean'] == pytest.approx(1., abs=1e-6)
    assert rows[0]['body_log_words'] == pytest.approx(np.log1p(64))
