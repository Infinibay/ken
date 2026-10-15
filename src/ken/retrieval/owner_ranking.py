"""Order canonical owners using pinned numeric models and source coverage."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
from importlib import import_module
from typing import Any

import numpy as np

from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES, SOURCE_VIEW_FEATURES, contextual_features
from ken.retrieval.description import OwnerDescription
from ken.retrieval.evidence_features import FEATURES, evidence_features
from ken.retrieval.model import Candidate, CodeMatch, EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.profile import RegisteredEncoder, EvidenceRanking
from ken.retrieval.ranking import rank_candidates
from ken.retrieval.tokenization import code_tokens


def _stem_one(word: str, factory: Callable[[str], Any]) -> str:
    # Snowball mutates its current word buffer; each miss owns its stemmer.
    return factory('english').stemWords([word])[0]


_stem_word = lru_cache(maxsize=32768)(_stem_one)


class EvidenceReranker:
    def __init__(self, model: NumericRanker, encoder: RegisteredEncoder, *,
                 expand_query: Callable[[str], str] | None = None,
                 expansion_revision: str | None = None):
        schemas = (FEATURES, (*FEATURES, *CONTEXTUAL_FEATURES),
                   (*FEATURES, *CONTEXTUAL_FEATURES, *SOURCE_VIEW_FEATURES))
        if model.features not in schemas:
            raise ValueError('numeric model uses an incompatible source feature schema')
        if (expand_query is None) != (expansion_revision is None):
            raise ValueError('query expansion requires its immutable revision')
        self.model, self.encoder = model, encoder
        self.feature_version = schemas.index(model.features) + 1
        self.expand_query, self.expansion_revision = expand_query, expansion_revision

    @staticmethod
    def stem_words(words: list[str]) -> list[str]:
        factory = import_module('snowballstemmer').stemmer
        return [_stem_word(word, factory) if len(word) <= 128 else _stem_one(word, factory)
                for word in words]

    def validate(self, spec: EvidenceRanking) -> None:
        if (self.model.fingerprint != spec.model_revision or self.encoder.spec != spec.word_model
                or self.expansion_revision != spec.expansion_revision
                or self.feature_version != spec.feature_version):
            raise ValueError('owner ranking runtime does not match its pinned profile')

    def prepare_query(self, query: str) -> str:
        expanded = self.expand_query(query) if self.expand_query else query
        if not isinstance(expanded, str) or not expanded.strip():
            raise ValueError('query expansion must return nonempty text')
        return expanded

    def rank(self, request: SearchRequest, candidates: Sequence[Candidate],
             descriptions: Mapping[EntityKey, OwnerDescription], *,
             expanded_query: str | None = None, evidence_version: int = 1) -> list[CodeMatch]:
        if evidence_version not in (1, 2):
            raise ValueError('unsupported source evidence policy')
        if len(candidates) == 1 and candidates[0].signals.get('exact'):
            return rank_candidates(request, list(candidates))
        expanded = self.prepare_query(request.query) if expanded_query is None else expanded_query
        matrix = evidence_features(request, candidates, descriptions, encoder=self.encoder,
            stem_words=self.stem_words, expanded_query=expanded)
        values = (np.column_stack((matrix.values, contextual_features(candidates,
            source_views=self.feature_version == 3).values))
                  if self.feature_version >= 2 else matrix.values)
        scores = self.model.predict(values)
        terms = set(code_tokens(expanded))
        def evidence(candidate: Candidate):
            if evidence_version == 2:
                return candidate.passages
            # Retrieval chunks propose an owner; every verified owned region
            # used for its score is also eligible to support its visible answer.
            retrieved = {p.span: p.signals for p in candidate.passages}
            return [replace(p, signals={**retrieved.get(p.span, p.signals),
                'joint_evidence': len(terms & set(code_tokens(p.fields['body']))) / max(1, len(terms))})
                for p in descriptions[candidate.entity].passages]
        matches = [CodeMatch(c.entity, float(score), evidence(c), c.passages[0].source_hash,
            {**c.signals, 'evidence_relevance': float(score)}, c.owned_regions)
            for c, score in zip(candidates, scores, strict=True)]
        # Stable ties preserve the proposal order rather than adding another
        # source-name prior that was absent from the trained ranking contract.
        return sorted(matches, key=lambda m: (-m.signals.get('exact', 0), -m.score))
