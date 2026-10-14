"""A vector view with stable ownership, ranked without grouping the whole corpus."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

import numpy as np

from ken.retrieval.embedding_store import IndexVersionError, VectorView
from ken.retrieval.model import Candidate, EntityKey, Passage


class DenseView:
    """Pin row ownership once with the immutable source/vector generation."""
    def __init__(self, passages: Mapping[int, Passage], vectors: VectorView):
        self.ids, self.matrix = vectors.ids, vectors.matrix
        self.passages = tuple(passages[pid] for pid in self.ids)
        indices: dict[EntityKey, int] = {}
        labels = []
        for passage in self.passages:
            if passage.entity not in indices:
                indices[passage.entity] = len(indices)
            labels.append(indices[passage.entity])
        self.entities = tuple(indices)
        self.labels = np.asarray(labels, dtype=np.int32)
        self.labels.setflags(write=False)

    def search(self, query: np.ndarray, view: str, limit: int) -> list[Candidate]:
        if self.matrix.ndim != 2 or query.ndim != 1 or self.matrix.shape[1] != query.size:
            raise IndexVersionError('query/vector dimensions differ; reindex the retrieval profile')
        if not np.isfinite(query).all() or float(np.linalg.norm(query)) <= 0:
            raise ValueError('encoder returned an invalid query vector')
        scores = self.matrix @ (query / np.linalg.norm(query))
        peaks = np.full(len(self.entities), -np.inf, dtype=scores.dtype)
        np.maximum.at(peaks, self.labels, scores)
        # Entities are numbered by first vector row, preserving stable score ties.
        selected = np.argsort(-peaks, kind='stable')[:limit]
        rows = np.flatnonzero(np.isin(self.labels, selected))
        rows = rows[np.argsort(-scores[rows], kind='stable')]
        evidence: dict[int, list[Passage]] = {int(owner): [] for owner in selected}
        for row in rows:
            owned = evidence[int(self.labels[row])]
            if len(owned) < 4:
                passage = self.passages[int(row)]
                owned.append(replace(passage, signals={**passage.signals, f'cosine_{view}': float(scores[row])}))
        return [Candidate(self.entities[int(owner)], evidence[int(owner)],
                          {f'cosine_{view}': float(peaks[owner])}) for owner in selected]
