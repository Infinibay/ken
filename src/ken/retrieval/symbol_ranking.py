"""Combine bounded source views and explicit symbol evidence inside native10."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from ken.retrieval.description import OwnerDescription, describe_owner
from ken.retrieval.model import EntityKey, SearchRequest
from ken.retrieval.neural_reranker import ONNXReranker
from ken.retrieval.piece_catalog import SourceCatalog
from ken.retrieval.source_operations import OperationWitnesses
from ken.retrieval.symbol_requirements import (requirements, is_test_case,
    prefer_operations, prefer_explicit_code_terms)

SYMBOL_POLICY = 'bounded-symbol-relations-v305'


@dataclass(frozen=True)
class SymbolRanking:
    order: list[int]
    code_scores: list[float]
    mean_scores: list[float]
    code_view_used: list[bool]
    witnesses: list[frozenset[str]]
    additional_inference: dict[str, Any]


def complete_code_view(description: OwnerDescription) -> str | None:
    """Whole exclusive owned regions or no second view; never a blind prefix."""
    key = description.entity
    body = description.fields['executable']
    text = '\n'.join([f'symbol {key.path} {key.qualname}', description.fields['signature'],
                      'Implementation:', body])
    return text if len(body.splitlines()) <= 64 and len(text) <= 12000 else None


class SymbolRanker:
    """Compose relevance views, then stable preferences from explicit evidence."""
    def __init__(self, catalog: SourceCatalog, neural: ONNXReranker,
                 descriptions: dict[EntityKey, OwnerDescription]):
        self.catalog, self.neural, self.descriptions = catalog, neural, descriptions
        self.operations = OperationWitnesses(catalog)

    def rank(self, request: SearchRequest, cards: Sequence[dict[str, Any]],
             expanded_query: str, original_scores: Sequence[float]) -> SymbolRanking:
        if len(cards) != len(original_scores) or len(cards) > 10:
            raise ValueError('one original score per native top10 symbol required')
        keys = [EntityKey(path=card['unit']['path'], **card['unit']['entity']) for card in cards]
        descriptions = []
        for key in keys:
            if key not in self.descriptions:
                self.descriptions[key] = describe_owner(self.catalog.owners[key])
            descriptions.append(self.descriptions[key])
        texts, accepted = [], []
        for description in descriptions:
            text = complete_code_view(description)
            used = text is not None and self.neural.pair_fits(expanded_query, text)
            texts.append(text if used else None)
            accepted.append(used)
        fresh = list(dict.fromkeys(text for text in texts if text is not None))
        fresh_scores, details = self.neural.score(expanded_query, fresh)
        lookup = dict(zip(fresh, fresh_scores, strict=True))
        code_scores = [lookup[text] if text is not None else float(original_scores[i]) for i, text in enumerate(texts)]
        means = [(float(original)+code)/2 for original, code in zip(original_scores, code_scores, strict=True)]
        order = sorted(range(len(cards)), key=lambda i: -means[i])
        required = requirements(request)
        witnesses = [self.operations.for_owner(key) for key in keys] if required.operations else [frozenset() for _ in keys]
        order = prefer_operations(required.operations, witnesses, order)
        if required.test_case:
            entries = [is_test_case(key, self.catalog) for key in keys]
            order.sort(key=lambda i: not entries[i])
        order = prefer_explicit_code_terms(request.query,
            [description.fields['executable'] for description in descriptions], order)
        return SymbolRanking(order, code_scores, means, accepted, witnesses, details)
