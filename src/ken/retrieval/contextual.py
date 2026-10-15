"""Retrieve one contextual family from a complete, immutable source-owner index."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from ken.retrieval.embedding_store import IndexVersionError
from ken.retrieval.model import Candidate, EntityKey, Passage, merge_spans
from ken.retrieval.profile import ContextualRetrieval, EncoderSpec, RegisteredEncoder
from ken.retrieval.source_views import SourceViewSnapshot


@dataclass(frozen=True)
class OwnerVectorSnapshot:
    model: EncoderSpec
    generation: int
    owners: tuple[EntityKey, ...]
    source_hashes: tuple[str, ...]
    matrix: np.ndarray
    projection_version: int = 1

    def __post_init__(self) -> None:
        if len(set(self.owners)) != len(self.owners) or len(self.source_hashes) != len(self.owners):
            raise ValueError('contextual vectors require unique owners and matching source hashes')
        if self.generation < 0 or self.projection_version != 1:
            raise ValueError('invalid contextual source generation or projection')
        versions: dict[str, str] = {}
        for owner, digest in zip(self.owners, self.source_hashes, strict=True):
            if not digest or versions.setdefault(owner.path, digest) != digest:
                raise ValueError('contextual owners contain mixed source versions')
        matrix = np.array(self.matrix, dtype=np.float32, copy=True)
        if (matrix.ndim != 2 or matrix.shape[0] != len(self.owners) or not matrix.size
                or not np.isfinite(matrix).all()
                or not np.allclose(np.linalg.norm(matrix, axis=1), 1., atol=1e-5)):
            raise ValueError('contextual source vectors must be finite and normalized')
        matrix.setflags(write=False)
        object.__setattr__(self, 'matrix', matrix)


@dataclass(frozen=True)
class ContextualScores:
    source: OwnerVectorSnapshot
    original: np.ndarray
    expanded: np.ndarray
    source_views: SourceViewSnapshot | None = None
    query_vectors: tuple[np.ndarray, np.ndarray] | None = None

    def propose(self, owners: Mapping[EntityKey, Sequence[Passage]], *,
                limit: int) -> list[Candidate]:
        if limit <= 0:
            raise ValueError('positive contextual proposal budget required')
        peaks = np.maximum(self.original, self.expanded)
        order = np.argsort(-peaks, kind='stable')[:limit]
        return [Candidate(self.source.owners[i], list(owners[self.source.owners[i]][:4]),
            {'cosine_code': float(peaks[i])},
            merge_spans(p.span for p in owners[self.source.owners[i]])) for i in order]

    def enrich(self, candidates: Sequence[Candidate]) -> None:
        """Measure every combined owner, including owners outside the code top-k."""
        lookup = {owner: i for i, owner in enumerate(self.source.owners)}
        for candidate in candidates:
            index = lookup.get(candidate.entity)
            if index is None or not candidate.passages or any(
                p.entity != candidate.entity or p.source_hash != self.source.source_hashes[index]
                    for p in candidate.passages):
                raise IndexVersionError('contextual candidate source changed; reindex owner vectors')
            a, b = float(self.original[index]), float(self.expanded[index])
            candidate.signals.update(cosine_code_original=a, cosine_code_expanded=b,
                                    cosine_code=max(a, b))
        if self.source_views is not None:
            if self.query_vectors is None:
                raise ValueError('source views require their original query vectors')
            self.source_views.enrich(candidates, *self.query_vectors)


class ContextualRetriever:
    def __init__(self, encoder: RegisteredEncoder, vectors: OwnerVectorSnapshot, *,
                 source_views: SourceViewSnapshot | None = None):
        if encoder.spec != vectors.model:
            raise ValueError('contextual encoder does not match its pinned source vectors')
        self.encoder, self.vectors = encoder, vectors
        if source_views is not None and (
                source_views.query_model != vectors.model
                or source_views.generation != vectors.generation or source_views.owners != vectors.owners
                or source_views.source_hashes != vectors.source_hashes
                or source_views.matrix.shape[1] != vectors.matrix.shape[1]):
            raise ValueError('source views must match the complete contextual owner source')
        self.source_views = source_views

    def score(self, query: str, expanded: str, owners: Mapping[EntityKey, Sequence[Passage]], *,
              generation: int, policy: ContextualRetrieval) -> ContextualScores:
        if policy.model != self.encoder.spec or policy.projection_version != self.vectors.projection_version:
            raise ValueError('contextual runtime does not match its pinned profile')
        if policy.view_model != (self.source_views.model if self.source_views else None):
            raise ValueError('source view runtime does not match its pinned profile')
        if generation != self.vectors.generation:
            raise IndexVersionError('contextual source generation changed; reindex owner vectors')
        if set(owners) != set(self.vectors.owners):
            raise IndexVersionError('contextual index must cover all source owners; reindex owner vectors')
        for entity, digest in zip(self.vectors.owners, self.vectors.source_hashes, strict=True):
            if not owners[entity] or any(p.entity != entity or p.source_hash != digest for p in owners[entity]):
                raise IndexVersionError('contextual owner source changed; reindex owner vectors')

        def encode(text: str) -> np.ndarray:
            vector = np.array(self.encoder.embed_query(text), dtype=np.float32, copy=True)
            norm = np.linalg.norm(vector)
            if (vector.shape != (self.vectors.matrix.shape[1],) or not np.isfinite(vector).all()
                    or not np.isfinite(norm) or norm <= 1e-9):
                raise ValueError('contextual query must have a finite, positive vector of the indexed dimension')
            return vector/norm

        query_vector = encode(query)
        expanded_vector = query_vector if expanded == query else encode(expanded)
        original = self.vectors.matrix @ query_vector
        translated = original if expanded == query else self.vectors.matrix @ expanded_vector
        original.setflags(write=False)
        translated.setflags(write=False)
        query_vector.setflags(write=False)
        expanded_vector.setflags(write=False)
        return ContextualScores(self.vectors, original, translated, self.source_views,
                                (query_vector, expanded_vector))
