from dataclasses import replace
import numpy as np
import pytest

from ken.retrieval.evidence_features import FEATURES
from ken.retrieval.model import Candidate, CodeMatch, EntityKey, Passage, SearchRequest, Span
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.profile import EncoderSpec

WORD_MODEL = EncoderSpec('test-words', 'a'*64, 'provided')


def candidate(name, score, body):
    entity = EntityKey('store.py', 'function', name)
    p = Passage(entity, Span(1, 2), {'identity': name, 'signature': name, 'documentation': '',
        'body': body, 'path': entity.path}, 'hash', Span(1, 2))
    return Candidate(entity, [p], {'rrf': score})


def test_profile_binds_numeric_model_and_preserves_legacy_serialization():
    from ken.retrieval.profile import EvidenceRanking, RetrievalProfile, EncoderSpec
    spec = EncoderSpec('example', 'a'*40)
    legacy = RetrievalProfile(spec, spec)
    assert 'evidence' not in legacy.to_dict()
    profile = replace(legacy, evidence=EvidenceRanking('b'*64, WORD_MODEL))
    assert RetrievalProfile.from_dict(profile.to_dict()) == profile
    assert profile.fingerprint != legacy.fingerprint
    with pytest.raises(ValueError, match='revision'):
        EvidenceRanking('latest', WORD_MODEL)


def test_profile_rejects_a_different_word_encoder_with_the_same_numeric_model():
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.profile import EvidenceRanking
    from tests.retrieval.test_evidence_features import Encoder

    encoder = Encoder(); encoder.spec = WORD_MODEL
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{'value': 0.}]})
    runtime = EvidenceReranker(model, encoder)
    with pytest.raises(ValueError, match='pinned'):
        runtime.validate(EvidenceRanking(model.fingerprint,
            replace(WORD_MODEL, revision='b'*64)))


def test_stemming_keeps_mutable_word_buffers_local_to_concurrent_queries(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    import ken.retrieval.owner_ranking as module

    barrier = Barrier(2)
    class StatefulStemmer:
        def stemWords(self, words):
            self.current = words
            barrier.wait(timeout=5)
            return self.current

    monkeypatch.setattr(module,'import_module',lambda name:
        SimpleNamespace(stemmer=lambda language:StatefulStemmer()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(module.EvidenceReranker.stem_words,[['running'],['waiting']]))
    assert results == [['running'],['waiting']]


def test_ranking_uses_complete_source_and_preserves_input_order_for_score_ties():
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.description import describe_owner
    from tests.retrieval.test_evidence_features import Encoder
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{
        'feature': FEATURES.index('expanded_implementation_exact'), 'threshold': .8,
        'left': {'value': 0.}, 'right': {'value': 1.}}]})
    first = candidate('mentions', .2, 'unrelated(values)')
    second = candidate('stores', .1, 'persist(durable, cookie)')
    encoder = Encoder(); encoder.spec = WORD_MODEL
    reranker = EvidenceReranker(model, encoder)
    matches = reranker.rank(SearchRequest('persist durable cookie'), [first, second],
        {c.entity: describe_owner(c.passages) for c in [first, second]})
    assert matches[0].entity == second.entity
    assert matches[0].signals['evidence_relevance'] == 1.
    assert model.fingerprint == NumericRanker.from_dict(model.to_dict()).fingerprint
    ties = reranker.rank(SearchRequest('missing'), [first, second],
        {c.entity: describe_owner(c.passages) for c in [first, second]})
    assert [m.entity for m in ties] == [first.entity, second.entity]


def test_unique_exact_identity_needs_no_word_vectors_or_expansion():
    from ken.retrieval.owner_ranking import EvidenceReranker
    class Forbidden:
        spec = WORD_MODEL
        def embed_passages(self, text):
            raise AssertionError('exact identity must stay encoder-free')
        embed_query = embed_passages
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{'value': 0.}]})
    exact = candidate('stores', 1., 'persist(cookie)'); exact.signals['exact'] = 1.
    ranker = EvidenceReranker(model, Forbidden(),
        expand_query=lambda text: (_ for _ in ()).throw(AssertionError('no expansion')),
        expansion_revision='d'*64)
    assert ranker.rank(SearchRequest('stores'), [exact], {})[0].entity == exact.entity


def test_visible_evidence_can_use_owned_source_absent_from_retrieval_chunks(tmp_path):
    import hashlib
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.description import describe_owner
    from ken.retrieval.presentation import present
    from tests.retrieval.test_evidence_features import Encoder

    lines = ['def store():', *['    # context']*98, '    persist(durable, cookie)']
    source = '\n'.join(lines)+'\n'; (tmp_path/'store.py').write_text(source)
    c = candidate('store', .1, '\n'.join(lines[:20]))
    first = replace(c.passages[0], span=Span(1,20), entity_span=Span(1,100),
        source_hash=hashlib.sha256(source.encode()).hexdigest())
    last = replace(first, span=Span(81,100), fields={**first.fields, 'body':'\n'.join(lines[80:])})
    c.passages = [first]; c.owned_regions = (Span(1,100),)
    encoder = Encoder(); encoder.spec = WORD_MODEL
    model = NumericRanker.from_dict({'schema':1, 'features': FEATURES, 'trees':[{'value':1.}]})
    request = SearchRequest('persist durable cookie')
    matches = EvidenceReranker(model,encoder).rank(request,[c],{c.entity:describe_owner([first,last])})
    response = present(matches,tmp_path,request,profile_version='test')
    assert any(f['start_line'] <= 100 <= f['end_line'] for f in response.results[0]['evidence'])


def test_public_search_dispatches_pinned_evidence_model_and_rejects_a_mismatch(tmp_path):
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.profile import EvidenceRanking
    from ken.retrieval.representations import index_embeddings
    from ken.retrieval.service import search
    from tests.retrieval.test_candidates import indexed, profile, Encoder
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{
        'feature': FEATURES.index('expanded_implementation_exact'), 'threshold': .8,
        'left': {'value': 0.}, 'right': {'value': 1.}}]})
    encoder = Encoder(); encoder.spec = WORD_MODEL
    runtime = EvidenceReranker(model, encoder,
        expand_query=lambda text: 'conflict sentinel', expansion_revision='d'*64)
    configured = replace(profile(), evidence=EvidenceRanking(model.fingerprint, WORD_MODEL, 'd'*64))
    with indexed(tmp_path) as conn:
        index_embeddings(conn, profile(), encoders={'identity': encoder, 'behavior': encoder})
        response = search(conn, tmp_path, SearchRequest('browser state'), profile=configured,
            encoders={'identity': encoder, 'behavior': encoder}, owner_ranker=runtime)
        assert response.results[0]['entity']['qualname'] == 'fail'
        assert response.profile_version == configured.fingerprint
        wrong = replace(configured, evidence=EvidenceRanking('c'*64, WORD_MODEL, 'd'*64))
        with pytest.raises(ValueError, match='pinned'):
            search(conn, tmp_path, SearchRequest('browser state'), profile=wrong,
                encoders={'identity': encoder, 'behavior': encoder}, owner_ranker=runtime)
        # Exact identity continues to work even when the optional ranker is absent.
        exact = search(conn, tmp_path, SearchRequest('persist_state'), profile=configured)
        assert exact.results[0]['entity']['qualname'] == 'persist_state'
