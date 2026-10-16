from collections import defaultdict
from pathlib import Path

import pytest
from ken.parsers import detect_language
from ken.retrieval.model import SearchRequest
from ken.retrieval.passages import extract_passages
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.piece_cards import build_card, card_text
from ken.retrieval.neural_reranker import ONNXReranker, RerankerAssets
from tests.retrieval.test_neural_reranker import registered_reranker


def make_catalog(tmp_path, files):
    owners = defaultdict(list)
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        language, parse = detect_language(Path(name))
        data = source.encode()
        for passage in extract_passages(data, parse(data, name), path=name, language=language):
            owners[passage.entity].append(passage)
    return SourceCatalog(tmp_path, owners)


def test_explicit_purpose_prevents_test_granularity_from_overriding_the_caller():
    from ken.retrieval.symbol_requirements import requirements
    assert requirements(SearchRequest('Which regression checks the value?')).test_case
    assert not requirements(SearchRequest('Which regression checks the value?', purpose='implementation')).test_case
    assert not requirements(SearchRequest('Where does a test helper construct a value?')).test_case


@pytest.mark.parametrize('query, expected', [
    ('Find a handler for AND and OR expressions.', {'and', 'or'}),
    ('Find a handler for `not` expressions.', {'not'}),
    ('Find a handler for token parsing and expression evaluation.', set()),
])
def test_only_explicit_code_operators_are_requirements(query, expected):
    from ken.retrieval.symbol_requirements import requirements
    assert requirements(SearchRequest(query)).operators == expected


def test_symbol_relation_breaks_a_wrong_score_preference_without_losing_candidates(tmp_path, registered_reranker):
    from ken.retrieval.symbol_ranking import SymbolRanker
    catalog = make_catalog(tmp_path / 'repo', {'sample.py': '''def wrapper(error):
    return str(error)

def annotate(error):
    raise AttributeError("location") from error
'''})
    keys = {k.qualname: k for k in catalog.owners}
    query = 'Find the attribute error that retains the original exception as its cause.'
    cards = [build_card(keys[name], 'symbol', [keys[name]], query, catalog) for name in ['wrapper', 'annotate']]
    neural = ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker))
    result = SymbolRanker(catalog, neural, {}).rank(SearchRequest(query), cards, query, [100., 0.])
    assert result.order == [1, 0]
    assert result.mean_scores[0] > result.mean_scores[1]
    assert result.witnesses[1] == frozenset({'cause:AttributeError'})


def test_oversize_complete_view_reuses_original_score_atomically(tmp_path, registered_reranker):
    from ken.retrieval.symbol_ranking import SymbolRanker
    source = 'def sample():\n' + ''.join(f'    value_{i} = {i}\n' for i in range(70))
    catalog = make_catalog(tmp_path / 'repo', {'sample.py': source})
    key = next(k for k in catalog.owners if k.qualname == 'sample')
    card = build_card(key, 'symbol', [key], 'sample', catalog)
    neural = ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker))
    original, _ = neural.score('sample', [card_text(card)])
    result = SymbolRanker(catalog, neural, {}).rank(SearchRequest('sample'), [card], 'sample', original)
    assert result.order == [0]
    assert result.code_view_used == [False]
    assert result.code_scores == original and result.mean_scores == original


def test_complete_pair_capacity_check_does_not_truncate_or_change_later_scoring(registered_reranker):
    neural = ONNXReranker(lambda: RerankerAssets.from_registration(registered_reranker), max_tokens=16)
    assert neural.pair_fits('x', 'y ' * 12)
    assert not neural.pair_fits('x', 'y ' * 13)
    assert neural.score('x', ['y'])[0] == [29.]
