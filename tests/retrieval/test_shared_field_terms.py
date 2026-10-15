"""Identical source fields need one tokenization; combined views keep their limits."""
from collections import Counter
import math

import pytest

from ken.retrieval.description import describe_owner
from ken.retrieval.model import Candidate, EntityKey, Passage, SearchRequest, Span
from tests.retrieval.test_evidence_features import Encoder


def owner(documentation='Store a durable cookie.'):
    entity = EntityKey('owned_store.py', 'function', 'store_cookie')
    fields = {'identity': 'function store_cookie', 'signature': 'def store_cookie(value):',
        'documentation': documentation, 'path': entity.path,
        'body': 'def store_cookie(value):\n    terminal(value)\n    return value'}
    passage = Passage(entity, Span(1, 3), fields, 'source-hash', Span(1, 3))
    return Candidate(entity, [passage]), describe_owner([passage])


def test_public_feature_factory_tokenizes_each_shared_owner_field_once(monkeypatch):
    import ken.retrieval.evidence_features as module

    candidate, description = owner()
    count = Counter()
    original = module.code_terms

    def measured(text, *, limit=None):
        count[text, limit] += 1
        return original(text, limit=limit)

    monkeypatch.setattr(module, 'code_terms', measured)
    result = module.evidence_features(SearchRequest('durable cookie'), [candidate],
        {candidate.entity: description}, encoder=Encoder(), stem_words=lambda words: words)
    assert result.values.shape == (1, len(result.names))
    for field in ('identity', 'signature', 'documentation', 'path'):
        assert count[description.fields[field], 4096] == 1


def test_combined_source_keeps_its_own_limit_instead_of_borrowing_raw_union():
    import ken.retrieval.evidence_features as module

    candidate, description = owner(' '.join(f'docword{i}' for i in range(4200)))
    result = module.evidence_features(SearchRequest('terminal'), [candidate],
        {candidate.entity: description}, encoder=Encoder(), stem_words=lambda words: words)
    values = dict(zip(result.names, result.values[0], strict=True))
    assert values['all_exact'] == 1.
    assert values['expanded_all_exact'] == 0.
    assert values['expanded_implementation_exact'] == 1.
    assert values['expanded_all_log_words'] == pytest.approx(math.log1p(4096))
