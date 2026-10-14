from dataclasses import replace

from ken.bench.ranking_controls import prefer_requested_role
from ken.retrieval.model import CodeMatch, SearchRequest
from tests.retrieval.test_ranking import candidate


def match(name, role, score):
    item = candidate(name, "body", role=role)
    return CodeMatch(item.entity, score, item.passages, item.passages[0].source_hash)


def test_role_control_reorders_without_adding_removing_or_changing_scores():
    implementation, test = match("work", "definition", 1.), match("check", "test", 2.)
    result = prefer_requested_role(SearchRequest("perform the operation"), [test, implementation])
    assert result == [implementation, test]
    assert {m.entity: m.score for m in result} == {m.entity: m.score for m in [test, implementation]}
    assert prefer_requested_role(SearchRequest("Which test covers the operation?"), result) == [test, implementation]


def test_role_control_never_overrides_exact_identity_or_natural_declaration_request():
    exact = replace(match("check", "test", 1.), signals={"exact": 1.})
    implementation = match("work", "definition", 2.)
    assert prefer_requested_role(SearchRequest("check"), [exact, implementation])[0] == exact
    assert prefer_requested_role(SearchRequest("Show the work function definition."), [exact, implementation]) == [exact, implementation]


def test_purpose_allocation_precedes_neural_budget_without_overriding_exact_identity():
    from ken.bench.ranking_controls import select_requested_role_candidates
    from tests.retrieval.test_ranking import candidate
    tests = [candidate('test_'+str(i),'call implementer()',role='test') for i in range(8)]
    implementation = candidate('implementer','actual operation')
    for t in tests:t.signals['rrf'] = 2.
    implementation.signals['rrf'] = 1.
    pool = [*tests,implementation]
    chosen = select_requested_role_candidates(SearchRequest('Where is the operation implemented?'),pool,limit=3)
    assert chosen[0] == implementation
    assert len(chosen) == 3
    assert select_requested_role_candidates(SearchRequest('Show the implementer function definition.'),pool,limit=3) == pool[:3]
    implementation.signals['exact'] = 1.
    assert select_requested_role_candidates(SearchRequest('Which test covers the operation?'),pool,limit=3)[0] == implementation
