"""Ranking context retains identity and adds only authenticated source."""
from copy import deepcopy
import hashlib

from ken.retrieval.model import EntityKey, Passage, Span
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.piece_cards import build_card, card_text
from verifiable_dependencies import LocalCallEvidence
from verifiable_pieces import validate_card
from contextual_ranking_card import ranking_context_card


def nested_catalog(root, *, account_for_child=True):
    lines = ['def validate(value):', '    if value is None:',
             '        raise ValueError("missing")', '    return value', '',
             'def outer(value):', '    def inner():',
             '        return validate(value)', '    return inner()']
    data = ('\n'.join(lines) + '\n').encode()
    (root / 'sample.py').write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    outer = EntityKey('sample.py', 'function', 'outer')
    helper = EntityKey('sample.py', 'function', 'validate')
    inner = EntityKey('sample.py', 'function', 'outer.inner')
    definitions = [(helper, [(1, 4)], (1, 4), 2),
                   (outer, [(6, 6), (9, 9)], (6, 9), 7)]
    if account_for_child:
        definitions.append((inner, [(7, 8)], (7, 8), 8))
    owners = {key: [Passage(key, Span(a, b), {'body': '\n'.join(lines[a-1:b])},
        digest, Span(*extent), implementation_start_line=implementation)
        for a, b in ranges] for key, ranges, extent, implementation in definitions}
    catalog = SourceCatalog(root, owners)
    card = build_card(outer, 'symbol', [outer], 'reject a missing value', catalog)
    return catalog, card, outer, inner, helper


def coordinates(card):
    return {(e['path'], n) for e in card['excerpts']
            for n in range(e['start_line'], e['end_line'] + 1)}


def test_lexical_scope_restores_nested_code_with_its_own_identity(tmp_path):
    catalog, card, outer, inner, _ = nested_catalog(tmp_path)
    original = deepcopy(card)
    result = ranking_context_card(card, 'reject a missing value', catalog, lexical_scope=True)
    assert coordinates(result) == {('sample.py', n) for n in range(6, 10)}
    assert result['unit']['entity'] == outer.to_dict()
    assert result['excerpts'][0]['included_entities'] == [inner.to_dict()]
    assert 'return validate(value)' in card_text(result)
    assert card == original
    validate_card(result, catalog)


def test_unaccounted_source_gap_keeps_original_projection(tmp_path):
    catalog, card, *_ = nested_catalog(tmp_path, account_for_child=False)
    assert ranking_context_card(card, 'reject a missing value', catalog, lexical_scope=True) is card


def test_calls_add_only_direct_visible_local_definition(tmp_path):
    catalog, card, outer, inner, helper = nested_catalog(tmp_path)
    resolver = LocalCallEvidence(catalog)
    result = ranking_context_card(card, 'reject a missing value', catalog, dependencies=resolver)
    supports = [e for e in result['excerpts'] if 'dependency' in e]
    assert [e['entity'] for e in supports] == [inner.to_dict()]
    assert supports[0]['dependency']['caller'] == outer.to_dict()
    assert 'raise ValueError' not in card_text(result)
    assert coordinates(result) >= coordinates(card)
    validate_card(result, catalog, dependencies=resolver)


def test_scope_makes_nested_call_visible_for_direct_dependency_evidence(tmp_path):
    catalog, card, outer, inner, helper = nested_catalog(tmp_path)
    resolver = LocalCallEvidence(catalog)
    result = ranking_context_card(card, 'reject a missing value', catalog,
                                 lexical_scope=True, dependencies=resolver)
    supports = [e for e in result['excerpts'] if 'dependency' in e]
    assert [e['entity'] for e in supports] == [helper.to_dict()]
    assert supports[0]['dependency']['caller'] == inner.to_dict()
    assert 'raise ValueError("missing")' in card_text(result)
    assert result['unit']['entity'] == outer.to_dict()
    assert coordinates(result) >= coordinates(card)
    validate_card(result, catalog, dependencies=resolver)


def test_aggregate_answer_does_not_switch_to_symbol_projection(tmp_path):
    catalog, _, outer, *_ = nested_catalog(tmp_path)
    card = build_card('sample.py', 'file', [outer], 'reject missing value', catalog)
    assert ranking_context_card(card, 'reject missing value', catalog,
        lexical_scope=True, dependencies=LocalCallEvidence(catalog)) is card


def test_no_available_context_keeps_exact_original_bytes(tmp_path):
    from test_verifiable_dependencies import fixture
    catalog, card, *_ = fixture(tmp_path, shadow=True)
    assert ranking_context_card(card, 'reject missing value', catalog,
        lexical_scope=True, dependencies=LocalCallEvidence(catalog)) is card


def test_unsupported_java_calls_add_no_guessed_context(tmp_path):
    lines = ['class Sample {', '  int validate(int value) { return value; }',
             '  int outer(int value) { return validate(value); }', '}']
    data = ('\n'.join(lines) + '\n').encode()
    (tmp_path / 'Sample.java').write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    keys = [EntityKey('Sample.java', 'method', name, 'Sample')
            for name in ['Sample.validate', 'Sample.outer']]
    owners = {key: [Passage(key, Span(n, n), {'body': lines[n-1]}, digest,
        Span(n, n), implementation_start_line=n)] for key, n in zip(keys, [2, 3])}
    catalog = SourceCatalog(tmp_path, owners)
    card = build_card(keys[1], 'symbol', [keys[1]], 'validate value', catalog)
    assert ranking_context_card(card, 'validate value', catalog,
        dependencies=LocalCallEvidence(catalog)) is card
