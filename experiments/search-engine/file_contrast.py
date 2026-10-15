"""Measure owner detail after accounting for its source file's common topic."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

COMMONNESS = ('log_file_owners', 'source_dot_mean', 'centered_norm', 'orthogonal_norm', 'topic_norm')
CONTRASTS = ('centered', 'orthogonal')


class FileContrast:
    def __init__(self, paths: Sequence[str], vectors: np.ndarray):
        values = np.array(vectors, dtype=np.float64, copy=True)
        if (values.ndim != 2 or not values.size or len(paths) != len(values)
                or not all(isinstance(path, str) and path for path in paths)
                or not np.isfinite(values).all()
                or not np.allclose(np.linalg.norm(values, axis=1), 1., atol=1e-5)):
            raise ValueError('one finite normalized source vector per owner path required')
        self.paths, groups = np.unique(paths, return_inverse=True)
        counts = np.bincount(groups)
        means = np.zeros((len(counts), values.shape[1]), dtype=np.float64)
        np.add.at(means, groups, values)
        means /= counts[:, None]
        mean_norms = np.linalg.norm(means, axis=1)
        topics = np.divide(means, mean_norms[:, None], out=np.zeros_like(means),
                           where=mean_norms[:, None] > 1e-9)
        source_mean, source_topic, centered_norm, orthogonal_norm = (
            np.empty(len(values)) for _ in range(4))
        for start in range(0, len(values), 4096):
            stop = start+4096
            rows, row_groups = values[start:stop], groups[start:stop]
            local_means, local_topics = means[row_groups], topics[row_groups]
            source_mean[start:stop] = np.einsum('ij,ij->i', rows, local_means)
            projected = np.einsum('ij,ij->i', rows, local_topics)
            source_topic[start:stop] = projected
            centered_norm[start:stop] = np.linalg.norm(rows-local_means, axis=1)
            orthogonal_norm[start:stop] = np.linalg.norm(rows-projected[:, None]*local_topics, axis=1)
        self.values, self.groups, self.means, self.topics = values, groups, means, topics
        self.mean_norms, self.source_mean, self.source_topic = mean_norms, source_mean, source_topic
        self.centered_norm, self.orthogonal_norm = centered_norm, orthogonal_norm
        self._commonness = np.column_stack((np.log1p(counts[groups]), source_mean,
            centered_norm, orthogonal_norm, mean_norms[groups]))
        for array in (values, groups, means, topics, mean_norms, source_mean, source_topic,
                      centered_norm, orthogonal_norm, self._commonness):
            array.setflags(write=False)

    def _indexes(self, owner_ids: Sequence[int]) -> np.ndarray:
        indexes = np.asarray(owner_ids)
        if not len(indexes):
            return np.empty(0, dtype=np.int64)
        if (indexes.ndim != 1 or indexes.dtype.kind not in 'iu'
                or np.any(indexes < 0) or np.any(indexes >= len(self.values))):
            raise ValueError('valid original owner row IDs required')
        return indexes

    def commonness(self, owner_ids: Sequence[int]) -> np.ndarray:
        return self._commonness[self._indexes(owner_ids)]

    def score(self, query: np.ndarray, owner_ids: Sequence[int]) -> np.ndarray:
        query = np.asarray(query, dtype=np.float64)
        if (query.shape != (self.values.shape[1],) or not np.isfinite(query).all()
                or not np.isclose(np.linalg.norm(query), 1., atol=1e-5)):
            raise ValueError('compatible finite normalized query vector required')
        ids = self._indexes(owner_ids)
        groups = self.groups[ids]
        # Subtract vectors before taking norms/dots: expanding squared norms
        # loses small differences when source directions are almost identical.
        local_means, local_topics = self.means[groups], self.topics[groups]
        query_centered = query-local_means
        source_centered = self.values[ids]-local_means
        query_orthogonal = query-(local_topics @ query)[:, None]*local_topics
        source_orthogonal = self.values[ids]-self.source_topic[ids, None]*local_topics
        centered = np.einsum('ij,ij->i', query_centered, source_centered)
        orthogonal = np.einsum('ij,ij->i', query_orthogonal, source_orthogonal)
        den_centered = np.linalg.norm(query_centered, axis=1)*self.centered_norm[ids]
        den_orthogonal = np.linalg.norm(query_orthogonal, axis=1)*self.orthogonal_norm[ids]
        centered = np.divide(centered, den_centered, out=np.zeros_like(centered),
                              where=den_centered > 1e-9)
        orthogonal = np.divide(orthogonal, den_orthogonal, out=np.zeros_like(orthogonal),
            where=(den_orthogonal > 1e-9) & (self.mean_norms[groups] > 1e-9))
        return np.column_stack((centered, orthogonal))
