"""Order requested pieces within native top10, then present current bounded source."""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ken.retrieval.description import OwnerDescription
from ken.retrieval.intent import requested_piece_kind, requested_piece_path
from ken.retrieval.model import CodeMatch, EntityKey, SearchRequest, SearchResponse
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.piece_candidates import assemble_pieces
from ken.retrieval.piece_cards import build_piece_cards, canonical, card_text, validate_card
from ken.retrieval.piece_catalog import SourceCatalog, module_name
from ken.retrieval.piece_ranking import PieceReranker
from ken.retrieval.reranker_fusion import fused_reranker_order
from ken.retrieval.symbol_ranking import SymbolRanker, SYMBOL_POLICY


def _unit(kind: str, path: str, entity: EntityKey | None) -> dict[str, Any]:
    return {'target_kind': kind, 'path': path, 'entity': entity.to_dict() if entity else None,
            'module_name': module_name(path) if kind == 'module' else None}


class PieceSearch:
    """Own the measured piece forest, fixed card projection and neural fusion."""
    def __init__(self, catalog: SourceCatalog, ranker: PieceReranker, neural: ONNXReranker):
        self.catalog, self.ranker, self.neural = catalog, ranker, neural
        self.descriptions: dict[EntityKey, OwnerDescription] = {}
        self.symbols = SymbolRanker(catalog, neural, self.descriptions)

    def search(self, request: SearchRequest, matches: Sequence[CodeMatch], *,
               expanded_query: str, profile_version: str, exact: bool = False) -> SearchResponse:
        kind = requested_piece_kind(request)
        cards = build_piece_cards(matches, kind, expanded_query, self.catalog)
        pieces = assemble_pieces(matches, kind, self.catalog, self.descriptions)
        ranked = self.ranker.rank(request, pieces, expanded_query=expanded_query)
        identities = {canonical(card['unit']): i for i, card in enumerate(cards[:10])}
        existing = [identities[canonical(_unit(m.piece.kind, m.piece.path, m.piece.entity))] for m in ranked]
        scores, details = (([0.] * len(existing), {}) if exact else
            self.neural.score(expanded_query, [card_text(cards[i]) for i in existing]))
        symbols = None
        if exact:
            local_order = list(range(len(existing)))
        elif kind == 'symbol':
            symbols = self.symbols.rank(request, [cards[i] for i in existing], expanded_query, scores)
            local_order = symbols.order
        else:
            local_order = fused_reranker_order(scores)
        order = [existing[i] for i in local_order]
        named_path = requested_piece_path(request)
        if named_path:
            order.sort(key=lambda i: cards[i]['unit']['path'] != named_path)
        if sorted(order) != list(range(min(10, len(cards)))):
            raise ValueError('piece reranking changed native top10 membership')
        response = present_cards([cards[i] for i in order], request, self.catalog,
                                 profile_version=profile_version)
        if request.explain:
            for result in response.results:
                identity = canonical(_unit(kind, result['path'],
                    EntityKey(path=result['path'], **result['entity']) if kind in {'class','symbol'} else None))
                i = identities[identity]
                j = existing.index(i)
                result['signals'] = {'native_piece_rank': i+1, 'piece_rank': j+1,
                    'piece_score': ranked[j].score, 'neural_score': scores[j],
                    'reranker': details}
                if symbols is not None:
                    result['signals']['symbol_ranking'] = {
                        'policy': SYMBOL_POLICY, 'code_view_used': symbols.code_view_used[j],
                        'code_score': symbols.code_scores[j], 'mean_score': symbols.mean_scores[j],
                        'source_operations': sorted(symbols.witnesses[j]),
                        'additional_reranker': symbols.additional_inference}
        return response


def present_cards(cards: Sequence[dict[str, Any]], request: SearchRequest, catalog: SourceCatalog, *,
                  profile_version: str) -> SearchResponse:
    """Keep primary identity independent from the member excerpt supporting it."""
    response = SearchResponse(request.query, [], profile_version)
    for card in cards[:request.limit]:
        unit = card['unit']; path, kind = unit['path'], unit['target_kind']
        entity = unit['entity'] or {'kind': kind, 'qualname': unit['module_name'],
                                    'owner': None, 'definition_ordinal': 0}
        if unit['entity']:
            start, end = catalog.extent(EntityKey(path=path, **unit['entity']))
        else:
            start, end = 1, max(1, len(catalog.lines[path]))
        result: dict[str, Any] = {'path': path, 'piece_kind': kind, 'entity': entity,
            'entity_span': {'start_line': start, 'end_line': end}, 'evidence': [],
            'source_hash': card['source_hash'], 'stale': False, 'truncated': card['truncated']}
        if kind == 'module':
            result['module_name'] = unit['module_name']
        try:
            validate_card(card, catalog)
            remaining = 64 if request.explain else 16
            for excerpt in card['excerpts']:
                if remaining <= 0:
                    result['truncated'] = True
                    break
                count = min(remaining, excerpt['end_line']-excerpt['start_line']+1)
                result['evidence'].append({'start_line': excerpt['start_line'],
                    'end_line': excerpt['start_line']+count-1,
                    'content': '\n'.join(excerpt['content'].split('\n')[:count])})
                result['truncated'] |= count < excerpt['end_line']-excerpt['start_line']+1
                remaining -= count
        except (OSError, ValueError, UnicodeError) as exc:
            result['stale'] = True
            result['evidence'] = []
            response.warnings.append(f'{path}: {exc}; reindex before quoting source')
        contiguous: list[dict[str, Any]] = []
        for fragment in result['evidence']:
            if contiguous and contiguous[-1]['end_line']+1 == fragment['start_line']:
                contiguous[-1]['end_line'] = fragment['end_line']
                contiguous[-1]['content'] += '\n'+fragment['content']
            else:
                contiguous.append(fragment)
        result['evidence'] = contiguous
        response.results.append(result)
    response.omitted_count = max(0, len(cards)-len(response.results))
    # Retain every returned identity while reducing lower-priority source first.
    def size() -> int:
        return len(json.dumps(response.to_dict(), ensure_ascii=False, separators=(',', ':')))
    while response.results and size() > request.max_chars:
        reducible = [r for r in reversed(response.results) if r['evidence']]
        if not reducible:
            response.results.pop()
            response.omitted_count += 1
        else:
            result = reducible[0]
            fragment = result['evidence'][-1]
            if fragment['start_line'] == fragment['end_line']:
                result['evidence'].pop()
            else:
                fragment['end_line'] -= 1
                fragment['content'] = '\n'.join(fragment['content'].split('\n')[:-1])
            result['truncated'] = True
        response.truncated = True
    response.truncated |= bool(response.omitted_count or any(r['truncated'] for r in response.results))
    return response
