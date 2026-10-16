"""A bounded source card should retain all owned code when it fits."""
from pathlib import Path
import hashlib

from ken.retrieval.model import EntityKey, Passage, Span
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.piece_cards import build_card, card_text, validate_card
from complete_owner_body import complete_owner_body


def catalog_for(tmp_path, lines, ranges, children=()):
    path = 'sample.py'
    data = ('\n'.join(lines) + '\n').encode()
    (tmp_path / path).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    key = EntityKey(path, 'function', 'outer')
    owners = {key: [Passage(key, Span(a, b), {'body': '\n'.join(lines[a-1:b])},
        digest, Span(1, len(lines)), implementation_start_line=2) for a, b in ranges]}
    for a, b, qualname in children:
        child = EntityKey(path, 'function', qualname)
        owners[child] = [Passage(child, Span(a, b), {'body': '\n'.join(lines[a-1:b])},
                                 digest, Span(a, b), implementation_start_line=a)]
    return SourceCatalog(tmp_path, owners), key


def physical_lines(card):
    return {n for e in card['excerpts'] for n in range(e['start_line'], e['end_line'] + 1)}


def test_short_owner_keeps_terminal_behavior_without_losing_current_evidence(tmp_path):
    lines = ['def outer(value):', '    # initial marker'] + ['    value += 1'] * 44 + ['    return value']
    catalog, key = catalog_for(tmp_path, lines, [(1, len(lines))])
    old = build_card(key, 'symbol', [key], 'initial marker', catalog)
    original_text = card_text(old)
    assert len(lines) not in physical_lines(old)
    new = complete_owner_body(old, catalog)
    assert physical_lines(new) == set(range(1, len(lines) + 1))
    assert physical_lines(new) >= physical_lines(old)
    assert new['unit'] == old['unit']
    assert card_text(old) == original_text
    assert not new['truncated']
    validate_card(new, catalog)


def test_disjoint_owned_regions_keep_caller_tail_and_exclude_nested_callable_body(tmp_path):
    lines = ['def outer(value):', '    # initial marker', '    value += 1',
             '    def inner():', '        return 999',
             '    result = inner()', '    assert result == 999', '    return result']
    catalog, key = catalog_for(tmp_path, lines, [(1, 3), (6, 8)], [(4, 5, 'outer.inner')])
    old = build_card(key, 'symbol', [key], 'initial marker', catalog)
    assert 8 not in physical_lines(old)
    new = complete_owner_body(old, catalog)
    assert physical_lines(new) == {1, 2, 3, 6, 7, 8}
    assert 4 not in physical_lines(new) and 5 not in physical_lines(new)
    assert new['truncated']  # Child code is still separate and intentionally absent.
    validate_card(new, catalog)


def test_owner_that_cannot_fit_retains_exact_original_projection(tmp_path):
    lines = ['def outer(value):'] + ['    value += 1'] * 100 + ['    return value']
    catalog, key = catalog_for(tmp_path, lines, [(1, len(lines))])
    old = build_card(key, 'symbol', [key], 'increment value', catalog)
    text = card_text(old)
    assert complete_owner_body(old, catalog) is old
    assert card_text(old) == text


def test_already_complete_card_is_byte_unchanged(tmp_path):
    lines = ['def outer(value):', '    return value + 1']
    catalog, key = catalog_for(tmp_path, lines, [(1, 2)])
    old = build_card(key, 'symbol', [key], 'increment value', catalog)
    assert complete_owner_body(old, catalog) is old


def test_aggregate_card_keeps_exact_existing_projection(tmp_path):
    lines = ['def outer(value):', '    return value + 1']
    catalog, key = catalog_for(tmp_path, lines, [(1, 2)])
    old = build_card('sample.py', 'file', [key], 'increment value', catalog)
    assert complete_owner_body(old, catalog) is old


def test_character_budget_keeps_original_instead_of_dropping_existing_evidence(tmp_path):
    lines = ['def outer(value):', '    value = "' + 'x' * 12500 + '"', '    return value']
    catalog, key = catalog_for(tmp_path, lines, [(1, 3)])
    old = build_card(key, 'symbol', [key], 'return value', catalog)
    assert complete_owner_body(old, catalog) is old


def test_more_owned_regions_than_excerpt_budget_keep_exact_original(tmp_path):
    lines = ['def outer(value):', '    # initial marker', '    value = 0']
    ranges, children = [(1, 3)], []
    for i in range(5):
        start = len(lines) + 1
        lines += [f'    def inner_{i}():', f'        return {i}']
        children.append((start, start + 1, f'outer.inner_{i}'))
        lines.append('    value += 1')
        ranges.append((len(lines), len(lines)))
    lines.append('    return value')
    ranges[-1] = (ranges[-1][0], len(lines))
    catalog, key = catalog_for(tmp_path, lines, ranges, children)
    old = build_card(key, 'symbol', [key], 'initial marker', catalog)
    assert complete_owner_body(old, catalog) is old
