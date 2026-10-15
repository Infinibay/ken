from dataclasses import replace

import numpy as np
import pytest

from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot
from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES
from ken.retrieval.evidence_features import FEATURES
from ken.retrieval.model import SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.profile import ContextualRetrieval, EncoderSpec, EvidenceRanking
from tests.retrieval.test_candidates import Encoder, indexed, profile

CONTEXT_MODEL = EncoderSpec('test/context', 'b'*64, 'provided')


class ContextEncoder:
    spec = CONTEXT_MODEL

    def __init__(self):
        self.calls = []

    def embed_query(self, query):
        self.calls.append(query)
        return np.array([0., 2.], dtype=np.float32)


def test_real_api_combines_public_expansion_and_all_source_context_once(tmp_path):
    from ken.retrieval.candidates import owner_passages
    from ken.retrieval.embedding_store import retrieval_snapshot
    from ken.retrieval.representations import index_embeddings
    from ken.retrieval.service import search

    words = Encoder(); words.spec = EncoderSpec('words', 'c'*64, 'provided')
    names = (*FEATURES, *CONTEXTUAL_FEATURES)
    model = NumericRanker.from_dict({'schema': 1, 'features': names, 'trees': [{
        'feature': names.index('code_original_raw'), 'threshold': .8,
        'left': {'value': 0.}, 'right': {'value': 1.}}]})
    expansions = []
    def expand(query):
        expansions.append(query)
        return 'conflict sentinel'
    ranker = EvidenceReranker(model, words, expand_query=expand, expansion_revision='d'*64)
    configured = replace(profile(), contextual=ContextualRetrieval(CONTEXT_MODEL),
        evidence=EvidenceRanking(model.fingerprint, words.spec, 'd'*64,
                                 feature_version=2, evidence_version=2))
    with indexed(tmp_path) as conn:
        index_embeddings(conn, profile(), encoders={'identity': words, 'behavior': words})
        with retrieval_snapshot(conn) as view:
            owners = owner_passages(conn)
            vectors = OwnerVectorSnapshot(CONTEXT_MODEL, view.generation, tuple(owners),
                tuple(ps[0].source_hash for ps in owners.values()),
                np.array([[0., 1.] if e.qualname == 'fail' else [1., 0.] for e in owners]))
        context_encoder = ContextEncoder()
        runtime = ContextualRetriever(context_encoder, vectors)
        response = search(conn, tmp_path, SearchRequest('browser state'), profile=configured,
            encoders={'identity': words, 'behavior': words}, owner_ranker=ranker,
            contextual_retriever=runtime)
        assert response.results[0]['entity']['qualname'] == 'fail'
        assert response.profile_version == configured.fingerprint
        assert expansions == ['browser state']
        assert context_encoder.calls == ['browser state', 'conflict sentinel']
        assert response.results[0]['evidence']
        with pytest.raises(ValueError, match='contextual'):
            search(conn, tmp_path, SearchRequest('browser state'), profile=configured,
                encoders={'identity': words, 'behavior': words}, owner_ranker=ranker)
        # A unique original identity bypasses every optional model and expander.
        before = list(expansions)
        exact = search(conn, tmp_path, SearchRequest('persist_state'), profile=configured)
        assert exact.results[0]['entity']['qualname'] == 'persist_state'
        assert expansions == before
