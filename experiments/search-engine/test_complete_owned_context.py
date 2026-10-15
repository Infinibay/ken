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
    from complete_owned_context import complete_owned_context

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
    from complete_owned_context import complete_owned_context

    entity = EntityKey('client.py', 'function', 'store')
    passage = Passage(entity, Span(2, 3), {'body': 'a\nb'}, 'unverified', Span(1, 80))
    match = CodeMatch(entity, 1., [passage], 'unverified', {})
    assert complete_owned_context(match, tmp_path) is match


def test_over_budget_owner_keeps_its_original_evidence(tmp_path):
    from complete_owned_context import complete_owned_context

    source = '\n'.join(['def store(value):']+['    step(value)']*40)+'\n'
    (tmp_path/'client.py').write_text(source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    entity = EntityKey('client.py', 'function', 'store')
    passage = Passage(entity, Span(2, 3), {'body': '    step(value)\n    step(value)'},
                      digest, Span(1, 41))
    match = CodeMatch(entity, 1., [passage], digest, {}, (Span(1, 41),))
    assert complete_owned_context(match, tmp_path) is match
