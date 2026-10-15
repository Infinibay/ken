from dataclasses import replace

import numpy as np
import pytest

from ken.retrieval.model import Candidate, EntityKey, Passage, Span
from ken.retrieval.profile import EncoderSpec

MODEL = EncoderSpec('test/context', 'b'*64, 'provided', batch_size=1)


class Encoder:
    spec = MODEL

    def __init__(self):
        self.calls = []

    def embed_query(self, query):
        self.calls.append(query)
        return np.array([2., 0.] if query == 'original' else [0., 3.], dtype=np.float32)


def source():
    entities = [EntityKey('source.py', 'function', f'operation_{i}') for i in range(3)]
    return {e: [Passage(e, Span(1+3*i, 2+3*i), {'body': 'implementation()'},
        'source-hash', Span(1+3*i, 2+3*i))] for i, e in enumerate(entities)}


def runtime():
    from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot

    owners = source()
    vectors = OwnerVectorSnapshot(MODEL, 7, tuple(owners),
        tuple('source-hash' for _ in owners), np.array([[1., 0.], [0., 1.], [.6, .8]]))
    return ContextualRetriever(Encoder(), vectors), owners


def policy():
    from ken.retrieval.profile import ContextualRetrieval
    return ContextualRetrieval(MODEL, channel_limit=2, broad_limit=8)


def test_public_query_proposes_from_all_owners_and_scores_owners_outside_its_top_channel():
    engine, owners = runtime()
    result = engine.score('original', 'expanded', owners, generation=7, policy=policy())
    proposed = result.propose(owners, limit=2)
    assert [c.entity for c in proposed] == list(owners)[:2]
    assert engine.encoder.calls == ['original', 'expanded']
    assert all(c.owned_regions == (owners[c.entity][0].span,) for c in proposed)
    outside = Candidate(list(owners)[2], owners[list(owners)[2]])
    result.enrich([outside])
    assert outside.signals['cosine_code_original'] == pytest.approx(.6)
    assert outside.signals['cosine_code_expanded'] == pytest.approx(.8)


def test_identical_query_text_uses_one_encoder_call_and_one_contextual_family():
    engine, owners = runtime()
    result = engine.score('original', 'original', owners, generation=7, policy=policy())
    assert engine.encoder.calls == ['original']
    np.testing.assert_array_equal(result.original, result.expanded)
    assert len(result.propose(owners, limit=20)) == len(owners)


def test_context_requires_the_pinned_model_generation_and_complete_source_ownership():
    from ken.retrieval.embedding_store import IndexVersionError

    engine, owners = runtime()
    with pytest.raises(IndexVersionError, match='generation'):
        engine.score('original', 'expanded', owners, generation=8, policy=policy())
    with pytest.raises(IndexVersionError, match='owners'):
        engine.score('original', 'expanded', dict(list(owners.items())[:2]), generation=7, policy=policy())
    changed = dict(owners)
    first = next(iter(changed))
    changed[first] = [replace(changed[first][0], source_hash='changed')]
    with pytest.raises(IndexVersionError, match='source'):
        engine.score('original', 'expanded', changed, generation=7, policy=policy())
    with pytest.raises(ValueError, match='pinned'):
        engine.score('original', 'expanded', owners, generation=7,
            policy=replace(policy(), model=replace(MODEL, revision='c'*64)))
    assert engine.encoder.calls == []


def test_vector_snapshot_owns_immutable_normalized_source_vectors():
    from ken.retrieval.contextual import OwnerVectorSnapshot

    owners = source();entities = tuple(owners);hashes = tuple('source-hash' for _ in entities)
    raw = np.array([[1., 0.], [0., 1.], [.6, .8]], dtype=np.float32)
    snapshot = OwnerVectorSnapshot(MODEL, 7, entities, hashes, raw)
    raw[:] = 0
    assert not snapshot.matrix.flags.writeable
    assert float(snapshot.matrix[0, 0]) == 1.
    with pytest.raises(ValueError, match='normalized'):
        OwnerVectorSnapshot(MODEL, 7, entities, hashes, np.ones((3, 2)))
    with pytest.raises(ValueError, match='owners'):
        OwnerVectorSnapshot(MODEL, 7, (entities[0],)*3, hashes, snapshot.matrix)


def test_profile_pins_contextual_source_policy_without_changing_legacy_profiles():
    from ken.retrieval.profile import EvidenceRanking, RetrievalProfile

    static = EncoderSpec('static', 'a'*64, 'provided')
    legacy = RetrievalProfile(static, static)
    assert 'contextual' not in legacy.to_dict()
    configured = replace(legacy, contextual=policy(),
        evidence=EvidenceRanking('d'*64, static, feature_version=2, evidence_version=2))
    assert RetrievalProfile.from_dict(configured.to_dict()) == configured
    assert configured.fingerprint != legacy.fingerprint
    with pytest.raises(ValueError, match='contextual'):
        replace(configured, contextual=None)
    with pytest.raises(ValueError, match='projection'):
        replace(policy(), projection_version=2)


def test_profile_includes_the_runtime_of_its_contextual_encoder_backend(monkeypatch):
    import ken.retrieval.profile as module
    from ken.retrieval.profile import EvidenceRanking, RetrievalProfile

    static = EncoderSpec('static', 'a'*64, 'provided')
    contextual = replace(policy(), model=replace(MODEL, backend='sentence-transformers'))
    configured = RetrievalProfile(static, static, contextual=contextual,
        evidence=EvidenceRanking('d'*64, static, feature_version=2, evidence_version=2))
    runtime = ['first']
    monkeypatch.setattr(module, '_backend_runtime', lambda backend:
        (('torch', runtime[0]),) if backend == 'sentence-transformers' else ())
    before = configured.fingerprint
    runtime[0] = 'second'
    assert configured.fingerprint != before
