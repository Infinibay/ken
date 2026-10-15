"""Separate source contributions reuse one query encoding and fixed proposals."""
from dataclasses import replace

import numpy as np
import pytest

from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot
from ken.retrieval.model import Candidate
from ken.retrieval.profile import EncoderSpec
from tests.retrieval.test_contextual_retrieval import Encoder, MODEL, source

VIEW_MODEL = EncoderSpec('test/views', 'c'*64, 'provided', batch_size=1)


def prepared(tmp_path):
    from ken.retrieval.source_views import SourceViewSnapshot

    owners = source()
    entities = tuple(owners)
    hashes = ('source-hash',)*len(entities)
    full = OwnerVectorSnapshot(MODEL, 7, entities, hashes,
        np.array([[1., 0.], [0., 1.], [.6, .8]], dtype=np.float32))
    file = tmp_path/'vectors.npy'
    np.save(file, np.array([[1., 0.], [0., 1.], [.6, .8]], dtype=np.float32))
    pool = np.load(file, mmap_mode='r')
    views = SourceViewSnapshot(VIEW_MODEL, 7, entities, hashes, pool,
        {'contract': np.array([1, 0, 2]), 'implementation': np.array([2, 0, 1])}, query_model=MODEL)
    return owners, full, views, pool


def test_api_reuses_query_vectors_and_scores_only_combined_owners(tmp_path):
    from ken.retrieval.profile import ContextualRetrieval

    owners, full, views, pool = prepared(tmp_path)
    encoder = Encoder()
    runtime = ContextualRetriever(encoder, full, source_views=views)
    policy = ContextualRetrieval(MODEL, view_model=VIEW_MODEL, channel_limit=1, broad_limit=4)
    result = runtime.score('original', 'expanded', owners, generation=7, policy=policy)
    assert [c.entity for c in result.propose(owners, limit=1)] == [next(iter(owners))]
    selected = [Candidate(e, owners[e]) for e in list(owners)[1:]]
    result.enrich(selected)
    assert encoder.calls == ['original', 'expanded']
    np.testing.assert_allclose(
        [c.signals['cosine_view_contract_original'] for c in selected], [1., .6])
    np.testing.assert_allclose(
        [c.signals['cosine_view_implementation_expanded'] for c in selected], [0., 1.])
    assert np.shares_memory(views.matrix, pool)
    assert not views.matrix.flags.writeable


def test_identical_query_and_empty_candidate_views_never_add_encoder_calls(tmp_path):
    from ken.retrieval.profile import ContextualRetrieval

    owners, full, views, _ = prepared(tmp_path)
    runtime = ContextualRetriever(Encoder(), full, source_views=views)
    result = runtime.score('original', 'original', owners, generation=7,
                          policy=ContextualRetrieval(MODEL, view_model=VIEW_MODEL))
    result.enrich([])
    assert runtime.encoder.calls == ['original']


def test_source_view_registration_cannot_be_stale_missing_or_relabelled(tmp_path):
    from ken.retrieval.profile import ContextualRetrieval

    owners, full, views, _ = prepared(tmp_path)
    runtime = ContextualRetriever(Encoder(), full, source_views=views)
    with pytest.raises(ValueError, match='view'):
        runtime.score('original', 'expanded', owners, generation=7,
                      policy=ContextualRetrieval(MODEL))
    assert runtime.encoder.calls == []
    for wrong in [replace(views, generation=8),
                  replace(views, query_model=replace(MODEL, revision='e'*64)),
                  replace(views, source_hashes=('changed',)*3),
                  replace(views, owners=views.owners[::-1])]:
        with pytest.raises(ValueError, match='source'):
            ContextualRetriever(Encoder(), full, source_views=wrong)


def test_separate_projection_cannot_be_relabelled_as_the_full_owner_model(tmp_path):
    from ken.retrieval.profile import ContextualRetrieval

    _, _, views, _ = prepared(tmp_path)
    with pytest.raises(ValueError, match='projection'):
        replace(views, model=MODEL)
    with pytest.raises(ValueError, match='projection'):
        ContextualRetrieval(MODEL, view_model=MODEL)


def test_source_view_pool_rejects_missing_views_and_invalid_vectors_or_rows(tmp_path):
    _, _, views, _ = prepared(tmp_path)
    for changes in [
        {'rows': {'contract': np.array([0, 1, 2])}},
        {'rows': {'contract': np.array([0, 1, 3]), 'implementation': np.array([0, 1, 2])}},
        {'rows': {'contract': np.array([0., 1., 2.]), 'implementation': np.array([0, 1, 2])}},
        {'matrix': np.ones((3, 2))},
    ]:
        with pytest.raises(ValueError):
            replace(views, **changes)
    mutable = np.array(views.matrix)
    detached = replace(views, matrix=mutable)
    mutable[:] = 0
    assert float(detached.matrix[0, 0]) == 1.


def test_profile_roundtrip_binds_new_views_without_changing_existing_profiles():
    from ken.retrieval.profile import ContextualRetrieval, EvidenceRanking, RetrievalProfile

    words = EncoderSpec('words', 'a'*64, 'provided')
    previous = RetrievalProfile(words, words, contextual=ContextualRetrieval(MODEL),
        evidence=EvidenceRanking('d'*64, words, feature_version=2, evidence_version=2))
    assert 'view_model' not in previous.to_dict()['contextual']
    configured = replace(previous, contextual=ContextualRetrieval(MODEL, view_model=VIEW_MODEL),
        evidence=replace(previous.evidence, feature_version=3))
    assert RetrievalProfile.from_dict(configured.to_dict()) == configured
    assert configured.fingerprint != previous.fingerprint
    with pytest.raises(ValueError, match='view'):
        replace(configured, contextual=ContextualRetrieval(MODEL))
    with pytest.raises(ValueError, match='view'):
        replace(previous, contextual=configured.contextual)


def test_source_view_features_keep_each_contribution_and_pool_order():
    from ken.retrieval.contextual_features import contextual_features, SOURCE_VIEW_FEATURES

    candidates = [Candidate(e, ps, {'cosine_code_original': .2, 'cosine_code_expanded': .4,
        'cosine_view_contract_original': value, 'cosine_view_contract_expanded': .3,
        'cosine_view_implementation_original': -value,
        'cosine_view_implementation_expanded': .5})
        for value, (e, ps) in zip((.5, .1, .5), source().items(), strict=True)]
    features = contextual_features(candidates, source_views=True)
    assert features.names[8:] == SOURCE_VIEW_FEATURES
    np.testing.assert_array_equal(features.values[:, 8], [.5, .1, .5])
    np.testing.assert_array_equal(features.values[:, 11], [1., 1/3, 1/2])
    assert contextual_features([], source_views=True).values.shape == (0, 24)
    del candidates[0].signals['cosine_view_contract_expanded']
    with pytest.raises(ValueError, match='contextual'):
        contextual_features(candidates, source_views=True)


def test_real_search_api_can_rank_by_own_contract_with_one_shared_encoder(tmp_path):
    from ken.retrieval.candidates import owner_passages
    from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES, SOURCE_VIEW_FEATURES
    from ken.retrieval.embedding_store import retrieval_snapshot
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.numeric_ranker import NumericRanker
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.profile import ContextualRetrieval, EvidenceRanking
    from ken.retrieval.representations import index_embeddings
    from ken.retrieval.service import search
    from ken.retrieval.source_views import SourceViewSnapshot
    from tests.retrieval.test_candidates import Encoder as WordEncoder, indexed, profile
    from tests.retrieval.test_contextual_search import CONTEXT_MODEL, ContextEncoder

    words = WordEncoder()
    words.spec = EncoderSpec('words', 'a'*64, 'provided')
    names = (*FEATURES, *CONTEXTUAL_FEATURES, *SOURCE_VIEW_FEATURES)
    model = NumericRanker.from_dict({'schema': 1, 'features': names, 'trees': [{
        'feature': names.index('view_contract_original_raw'), 'threshold': .8,
        'left': {'value': 0.}, 'right': {'value': 1.}}]})
    ranker = EvidenceReranker(model, words, expand_query=lambda _: 'conflict sentinel',
                             expansion_revision='d'*64)
    configured = replace(profile(), contextual=ContextualRetrieval(CONTEXT_MODEL, view_model=VIEW_MODEL),
        evidence=EvidenceRanking(model.fingerprint, words.spec, 'd'*64,
                                 feature_version=3, evidence_version=2))
    with indexed(tmp_path) as conn:
        index_embeddings(conn, profile(), encoders={'identity': words, 'behavior': words})
        owners = owner_passages(conn)
        entities = tuple(owners)
        hashes = tuple(ps[0].source_hash for ps in owners.values())
        with retrieval_snapshot(conn) as snapshot:
            generation = snapshot.generation
        full = OwnerVectorSnapshot(CONTEXT_MODEL, generation, entities, hashes,
                                   np.array([[1., 0.]]*len(entities)))
        views = SourceViewSnapshot(VIEW_MODEL, generation, entities, hashes,
            np.eye(2, dtype=np.float32), {
                'contract': np.array([int(e.qualname == 'fail') for e in entities]),
                'implementation': np.zeros(len(entities), dtype=int)}, query_model=CONTEXT_MODEL)
        encoder = ContextEncoder()
        runtime = ContextualRetriever(encoder, full, source_views=views)
        response = search(conn, tmp_path, SearchRequest('browser state'), profile=configured,
            encoders={'identity': words, 'behavior': words}, owner_ranker=ranker,
            contextual_retriever=runtime)
        assert response.results[0]['entity']['qualname'] == 'fail'
        assert encoder.calls == ['browser state', 'conflict sentinel']
        before = list(encoder.calls)
        exact = search(conn, tmp_path, SearchRequest('persist_state'), profile=configured)
        assert exact.results[0]['entity']['qualname'] == 'persist_state'
        assert encoder.calls == before
