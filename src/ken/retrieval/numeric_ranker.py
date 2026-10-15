"""Run a validated numeric ranking forest without a training framework."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class _Tree:
    value: float | None = None
    feature: int = 0
    threshold: float = 0.
    left: _Tree | None = None
    right: _Tree | None = None

    @classmethod
    def parse(cls, data: Mapping[str, Any], size: int, depth: int = 0) -> _Tree:
        if depth > 64:
            raise ValueError('ranking tree exceeds supported depth')
        if set(data) == {'value'}:
            value = float(data['value'])
            if not math.isfinite(value):
                raise ValueError('finite leaf value required')
            return cls(value=value)
        if set(data) != {'feature', 'threshold', 'left', 'right'}:
            raise ValueError('unsupported ranking tree schema')
        feature = data['feature']
        if not isinstance(feature, int) or not 0 <= feature < size:
            raise ValueError('ranking tree references an unknown feature')
        threshold = float(data['threshold'])
        if not math.isfinite(threshold):
            raise ValueError('finite split threshold required')
        return cls(feature=feature, threshold=threshold,
                   left=cls.parse(data['left'], size, depth+1),
                   right=cls.parse(data['right'], size, depth+1))

    def to_dict(self) -> dict[str, Any]:
        if self.value is not None:
            return {'value': self.value}
        assert self.left is not None and self.right is not None
        return {'feature': self.feature, 'threshold': self.threshold,
                'left': self.left.to_dict(), 'right': self.right.to_dict()}


@dataclass(frozen=True)
class NumericRanker:
    features: tuple[str, ...]
    _trees: tuple[_Tree, ...]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NumericRanker:
        if data.get('schema') != 1:
            raise ValueError('unsupported numeric ranking schema')
        features = tuple(data['features'])
        if (not 1 <= len(features) <= 512 or len(set(features)) != len(features)
                or not all(isinstance(name, str) and name for name in features)):
            raise ValueError('unique named ranking features required')
        trees = data['trees']
        if not 1 <= len(trees) <= 4096:
            raise ValueError('bounded nonempty ranking forest required')
        return cls(features, tuple(_Tree.parse(t, len(features)) for t in trees))

    def to_dict(self) -> dict[str, Any]:
        return {'schema': 1, 'features': list(self.features),
                'trees': [t.to_dict() for t in self._trees]}

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.features):
            raise ValueError('ranking feature schema mismatch')
        if not np.isfinite(matrix).all():
            raise ValueError('finite ranking features required')
        result = np.zeros(len(matrix), dtype=np.float64)
        for tree in self._trees:
            pending = [(tree, np.arange(len(matrix)))]
            while pending:
                node, indices = pending.pop()
                if not len(indices):
                    continue
                if node.value is not None:
                    result[indices] += node.value
                else:
                    assert node.left is not None and node.right is not None
                    left = matrix[indices, node.feature] <= node.threshold
                    pending.extend(((node.left, indices[left]), (node.right, indices[~left])))
        return result
