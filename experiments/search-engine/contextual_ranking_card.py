"""Compose existing source context for ranking without changing answer identity.

This research projection reuses the lexical-scope and same-file-call evidence
contracts. It neither summarizes source nor infers execution of nested code.
Display cards remain separate. No model scores or expected answers enter here.
"""
from ken.retrieval.model import EntityKey
from verifiable_dependencies import enrich_card
from verifiable_pieces import _complete_scope_card, validate_card


def _coordinates(card):
    return {(e['path'], n) for e in card['excerpts']
            for n in range(e['start_line'], e['end_line'] + 1)}


def ranking_context_card(card, query, catalog, *, lexical_scope=False, dependencies=None):
    """Add bounded literal context, preserving every original physical line."""
    if card['unit']['target_kind'] != 'symbol':
        return card
    validate_card(card, catalog)
    result = card
    if lexical_scope:
        key = EntityKey(path=card['unit']['path'], **card['unit']['entity'])
        complete = _complete_scope_card(key, card, catalog)
        if complete is not None and _coordinates(complete) > _coordinates(card):
            result = complete
    if dependencies is not None:
        result = enrich_card(result, query, catalog, dependencies)
    if _coordinates(result) == _coordinates(card):
        return card  # Do not change only formatting or provenance labels.
    if not _coordinates(result) >= _coordinates(card) or result['unit'] != card['unit']:
        raise ValueError('ranking context lost primary evidence or changed identity')
    validate_card(result, catalog, dependencies=dependencies)
    return result
