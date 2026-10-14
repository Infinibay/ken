from dataclasses import replace

import pytest

from ken.bench.query_expansion import facet_queries, combine_proposals
from ken.retrieval.model import Candidate, SearchRequest, Span
from tests.retrieval.test_ranking import candidate


def test_query_facets_keep_original_and_literal_slices_without_splitting_quotes():
    text = 'Where does code retain "a b c d" and not discard values before checking the required owner?'
    queries = facet_queries(SearchRequest(text), width=8, max_facets=4)
    assert queries[0] == text
    assert 1 < len(queries) <= 5
    assert all(q in text for q in queries)
    assert all('"' not in q or '"a b c d"' in q for q in queries)
    assert facet_queries(SearchRequest('Show the Parser class declaration.')) == ['Show the Parser class declaration.']
    assert facet_queries(SearchRequest('Owner.method')) == ['Owner.method']


def test_proposal_budget_keeps_primary_coverage_and_deduplicates_owner_evidence():
    base = [candidate('base_'+str(i),'body') for i in range(4)]
    extra = candidate('helper','decisive body')
    repeated = replace(base[0],passages=[replace(base[0].passages[0],span=Span(2,3))])
    result = combine_proposals([base,[extra,repeated],[extra]], limit=4, primary_quota=2)
    assert len(result) == 4
    assert {c.entity for c in base[:2]} <= {c.entity for c in result}
    assert extra.entity in {c.entity for c in result}
    assert len({c.entity for c in result}) == len(result)
    merged = next(c for c in result if c.entity==base[0].entity)
    assert {p.span for p in merged.passages} == {Span(1,3),Span(2,3)}
    assert base[0].passages[0].signals == {}  # inputs were not rewritten
    assert merged.signals['rrf'] == pytest.approx(sum(merged.signals[k] for k in merged.signals if k.startswith('proposal_')))


def test_proposal_union_rejects_mixed_source_generations():
    first = candidate('same','body')
    changed = replace(first,passages=[replace(first.passages[0],source_hash='b'*64)])
    with pytest.raises(ValueError,match='source'):
        combine_proposals([[first],[changed]],limit=10,primary_quota=5)


def test_initial_proposal_also_rejects_mixed_source_evidence():
    first = candidate('same','body')
    first.passages.append(replace(first.passages[0],span=Span(2,3),source_hash='b'*64))
    with pytest.raises(ValueError,match='source'):
        combine_proposals([[first],[]],limit=10,primary_quota=5)
