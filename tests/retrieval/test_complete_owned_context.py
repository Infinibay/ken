import hashlib

import pytest

from ken.retrieval.model import CodeMatch, EntityKey, Passage, SearchRequest, Span
from ken.retrieval.presentation import present


@pytest.mark.parametrize('regions, query', [
    ((Span(1, 5), Span(41, 74)), 'validate and persist'),
    ((Span(1, 4), Span(41, 76)), 'validate and persist'),
    ((Span(1, 5), Span(41, 74)), 'different behavior words'),
])
def test_complete_owned_source_uses_unequal_fragment_budgets_when_it_fits(tmp_path, regions, query):
    from ken.retrieval.evidence import complete_owned_context

    lines = ['def store(value):'] + ['    other(value)']*79
    lines[1], lines[regions[-1].end_line-1] = '    validate(value)', '    persist(value)'
    source = '\n'.join(lines)+'\n'
    (tmp_path/'client.py').write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    entity = EntityKey('client.py', 'function', 'store')
    evidence = [Passage(entity, span, {'body': '\n'.join(lines[span.start_line-1:span.end_line])},
        digest, Span(1, 80), implementation_start_line=2) for span in regions]
    match = CodeMatch(entity, 9., evidence, digest, {}, regions)
    request = SearchRequest(query)
    refined = [complete_owned_context(match, tmp_path)]
    result = present(refined, tmp_path, request, profile_version='test').results[0]
    shown = {n for f in result['evidence'] for n in range(f['start_line'], f['end_line']+1)}
    owned = {n for r in regions for n in range(r.start_line, r.end_line+1)}
    assert shown == owned
    assert len(shown) <= 40
    assert refined[0].entity == entity and refined[0].score == 9.
    assert all(f['content'] == '\n'.join(lines[f['start_line']-1:f['end_line']])
               for f in result['evidence'])


def test_unproven_ownership_does_not_expand_a_retrieved_chunk(tmp_path):
    from ken.retrieval.evidence import complete_owned_context

    entity = EntityKey('client.py', 'function', 'store')
    passage = Passage(entity, Span(2, 3), {'body': 'a\nb'}, 'unverified', Span(1, 80))
    match = CodeMatch(entity, 1., [passage], 'unverified', {})
    assert complete_owned_context(match, tmp_path) is match


def test_over_budget_owner_keeps_its_original_evidence(tmp_path):
    from ken.retrieval.evidence import complete_owned_context

    source = '\n'.join(['def store(value):']+['    step(value)']*40)+'\n'
    (tmp_path/'client.py').write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    entity = EntityKey('client.py', 'function', 'store')
    passage = Passage(entity, Span(2, 3), {'body': '    step(value)\n    step(value)'},
                      digest, Span(1, 41))
    match = CodeMatch(entity, 1., [passage], digest, {}, (Span(1, 41),))
    assert complete_owned_context(match, tmp_path) is match


def test_complete_context_is_a_distinct_roundtripping_profile_policy():
    from dataclasses import replace
    from ken.retrieval.profile import EncoderSpec, EvidenceRanking, RetrievalProfile

    spec = EncoderSpec('test/provided', 'a'*64, 'provided')
    legacy = RetrievalProfile(spec, spec, evidence=EvidenceRanking('b'*64, spec, evidence_version=2))
    complete = replace(legacy, evidence=replace(legacy.evidence, evidence_version=3))
    assert complete.fingerprint != legacy.fingerprint
    assert RetrievalProfile.from_dict(complete.to_dict()) == complete
    assert legacy.to_dict()['evidence']['evidence_version'] == 2


def test_implementation_completion_leaves_documentation_requests_unchanged(tmp_path):
    from ken.retrieval.evidence import complete_evidence

    request = SearchRequest('Describe how values are persisted', purpose='documentation')
    entity = EntityKey('client.py', 'function', 'store')
    passage = Passage(entity, Span(2, 3), {'body': 'docs'}, 'hash', Span(1, 4))
    matches = [CodeMatch(entity, 1., [passage], 'hash', {}, (Span(1, 4),))]
    assert complete_evidence(matches, tmp_path, request) is matches


def test_public_search_completes_only_owned_source_under_explicit_policy(tmp_path):
    from dataclasses import replace
    from pathlib import Path
    import numpy as np
    from ken.db import connect, init_schema
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.indexing import index_project
    from ken.retrieval.numeric_ranker import NumericRanker
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.profile import EncoderSpec, EvidenceRanking, RetrievalProfile
    from ken.retrieval.service import search

    lines = ['def store(value):', '    validate(value)', *['    # setup']*3,
             '    def child():', *['        child(value)']*35,
             '    persist(value)', *['    step(value)']*32]
    source = '\n'.join(lines)+'\n'
    (tmp_path/'client.py').write_text(source)
    spec = EncoderSpec('test/provided', 'a'*64, 'provided')
    class Encoder:
        def embed_passages(self, texts):
            return [np.array([1., 0.], dtype=np.float32) for _ in texts]
        def embed_query(self, text):
            return np.array([1., 0.], dtype=np.float32)
    encoder = Encoder()
    encoder.spec = spec
    baseline = RetrievalProfile(spec, spec)
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{
        'feature': FEATURES.index('expanded_implementation_exact'), 'threshold': .8,
        'left': {'value': 0.}, 'right': {'value': 1.}}]})
    ranker = EvidenceReranker(model, encoder)
    configured = replace(baseline, evidence=EvidenceRanking(model.fingerprint, spec, evidence_version=3))
    request = SearchRequest('validate persist store')
    with connect(tmp_path/'index.db') as conn:
        init_schema(conn)
        index_project(conn, tmp_path, [Path('client.py')], profile=baseline,
                      encoders={'identity': encoder, 'behavior': encoder})
        response = search(conn, tmp_path, request, profile=configured,
                          encoders={'identity': encoder, 'behavior': encoder}, owner_ranker=ranker)
        result = response.results[0]
        assert result['entity']['qualname'] == 'store'
        visible = {n for f in result['evidence'] for n in range(f['start_line'], f['end_line']+1)}
        assert visible == set(range(1, 6)) | set(range(42, 75))
        assert response.profile_version == configured.fingerprint
        for f in result['evidence']:
            assert f['content'] == '\n'.join(lines[f['start_line']-1:f['end_line']])
        old = replace(configured, evidence=replace(configured.evidence, evidence_version=2))
        old_response = search(conn, tmp_path, request, profile=old,
            encoders={'identity': encoder, 'behavior': encoder}, owner_ranker=ranker)
        assert old_response.results[0]['entity'] == result['entity']
        assert old_response.results[0]['ranking_score'] == result['ranking_score']
        assert old_response.results[0]['evidence'] != result['evidence']


@pytest.mark.parametrize('target, complete_last', [('file', True), ('symbol', False)])
def test_completion_applies_to_the_actual_displayed_owners(tmp_path, target, complete_last):
    from ken.retrieval.evidence import complete_evidence

    first_source = 'def first():\n    pass\n\ndef second():\n    pass\n'
    (tmp_path/'a.py').write_text(first_source)
    digest = hashlib.sha256(first_source.encode()).hexdigest()
    matches = []
    for name, line in (('first', 1), ('second', 4)):
        entity = EntityKey('a.py', 'function', name)
        passage = Passage(entity, Span(line, line), {'body': first_source.splitlines()[line-1]},
                          digest, Span(line, line+1))
        matches.append(CodeMatch(entity, 3.-line, [passage], digest, {}, (Span(line, line+1),)))
    lines = ['def store(value):', '    validate(value)', *['    # setup']*3,
             '    def child():', *['        child(value)']*35,
             '    persist(value)', *['    step(value)']*32]
    source = '\n'.join(lines)+'\n'
    (tmp_path/'b.py').write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    entity = EntityKey('b.py', 'function', 'store')
    passage = Passage(entity, Span(1, 5), {'body': '\n'.join(lines[:5])}, digest, Span(1, 74))
    matches.append(CodeMatch(entity, -3., [passage], digest, {}, (Span(1, 5), Span(42, 74))))
    request = SearchRequest('validate then persist the value', target=target, limit=2)
    refined = complete_evidence(matches, tmp_path, request)
    assert [m.entity for m in refined] == [m.entity for m in matches]
    if complete_last:
        assert [p.span for p in refined[-1].evidence] == [Span(1, 5), Span(42, 74)]
        assert refined[1] is matches[1]
        response = present(refined, tmp_path, request, profile_version='test')
        assert [r['path'] for r in response.results] == ['a.py', 'b.py']
        assert len(response.results[-1]['evidence']) == 2
    else:
        assert refined[-1] is matches[-1]
