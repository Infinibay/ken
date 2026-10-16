import pytest

from ken.retrieval.intent import interpret
from ken.retrieval.model import SearchRequest


def test_request_keeps_explicit_piece_kind_separate_from_legacy_target():
    request = SearchRequest('find the requested behavior', piece_kind='class')
    assert request.target == 'symbol'
    assert request.piece_kind == 'class'
    with pytest.raises(ValueError, match='piece kind'):
        SearchRequest('behavior', piece_kind='unrecognized')


@pytest.mark.parametrize('query,expected', [
    ('Which HTML rendering class emits checkboxes?', 'class'),
    ('¿Qué clase representa un bloque de excepciones?', 'class'),
    ('Which importable module builds serializers?', 'module'),
    ('¿Qué módulo contiene las definiciones del decorador?', 'module'),
    ('Which physical Java source file declares the annotation?', 'file'),
    ('Where does this function use a class to serialize data?', 'symbol'),
])
def test_requested_piece_noun_reaches_ranking_without_exact_lookup_authority(query, expected):
    from ken.retrieval.intent import requested_piece_kind
    request = SearchRequest(query)
    assert requested_piece_kind(request) == expected
    assert not interpret(request).identity


def test_explicit_piece_kind_and_file_scope_override_query_inference():
    from ken.retrieval.intent import requested_piece_kind
    assert requested_piece_kind(SearchRequest('Which class builds this?', piece_kind='module')) == 'module'
    assert requested_piece_kind(SearchRequest('Which class builds this?', target='file')) == 'file'


def test_named_file_path_is_distinct_from_a_path_mentioned_in_behavior():
    from ken.retrieval.intent import requested_piece_path
    assert requested_piece_path(SearchRequest('Find src/Rules.java and show its factory.')) == 'src/Rules.java'
    assert requested_piece_path(SearchRequest('Mostrame `src/rules.py`.')) == 'src/rules.py'
    assert requested_piece_path(SearchRequest('Which file imports src/rules.py?')) is None
    assert requested_piece_path(SearchRequest('Find the function using src/rules.py.')) is None


def test_rank_trace_preserves_the_requested_piece_without_repurposing_legacy_features():
    from ken.retrieval.description import describe_owner
    from ken.retrieval.evidence_features import FEATURES
    from ken.retrieval.numeric_ranker import NumericRanker
    from ken.retrieval.owner_ranking import EvidenceReranker
    from ken.retrieval.ranking_trace import RankingTrace
    from tests.retrieval.test_evidence_features import Encoder
    from tests.retrieval.test_owner_ranking import candidate, WORD_MODEL

    encoder = Encoder(); encoder.spec = WORD_MODEL
    model = NumericRanker.from_dict({'schema': 1, 'features': FEATURES, 'trees': [{'value': 1.}]})
    ranker = EvidenceReranker(model, encoder)
    candidates = [candidate('build', .3, 'build(value)')]
    descriptions = {c.entity: describe_owner(c.passages) for c in candidates}
    trace = RankingTrace()
    request = SearchRequest('Which class builds values?', piece_kind='class')
    ranked = ranker.rank(request, candidates, descriptions, trace=trace)
    data = trace.to_dict()
    assert data['requested_piece_kind'] == 'class'
    assert data['owners'][0]['feature_values'][FEATURES.index('query_kind_class')] == 0.
    assert RankingTrace.from_dict(data, model).to_dict() == data
    assert ranked == ranker.rank(request, candidates, descriptions)
