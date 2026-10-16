"""Run a validated numeric ranking forest without a training framework."""
from __future__ import annotations

import math
import hashlib
import json
from functools import cached_property
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

    def explain(self, row: np.ndarray, features: tuple[str, ...]) -> tuple[float, list[dict[str, Any]]]:
        node = self
        path: list[dict[str, Any]] = []
        while node.value is None:
            value = float(row[node.feature])
            left = value <= node.threshold
            path.append({'feature': features[node.feature], 'feature_index': node.feature,
                         'value': value, 'threshold': node.threshold,
                         'branch': 'left' if left else 'right'})
            assert node.left is not None and node.right is not None
            node = node.left if left else node.right
        return node.value, path


@dataclass(frozen=True)
class _ArrayForest:
    """Traverse small batches across all trees with bounded NumPy scratch space."""
    roots: np.ndarray
    features: np.ndarray
    thresholds: np.ndarray
    left: np.ndarray
    right: np.ndarray
    values: np.ndarray

    @classmethod
    def compile(cls, trees: tuple[_Tree, ...]) -> _ArrayForest:
        features: list[int] = []
        thresholds: list[float] = []
        left: list[int] = []
        right: list[int] = []
        values: list[float] = []

        def add(node: _Tree) -> int:
            index = len(features)
            features.append(node.feature if node.value is None else -1)
            thresholds.append(node.threshold)
            left.append(index)
            right.append(index)
            values.append(node.value if node.value is not None else 0.)
            if node.value is None:
                assert node.left is not None and node.right is not None
                left[index], right[index] = add(node.left), add(node.right)
            return index

        roots = np.array([add(tree) for tree in trees], dtype=np.intp)
        arrays = (roots, np.asarray(features, dtype=np.intp), np.asarray(thresholds),
                  np.asarray(left, dtype=np.intp), np.asarray(right, dtype=np.intp),
                  np.asarray(values))
        for array in arrays:
            array.setflags(write=False)
        return cls(*arrays)

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        result = np.empty(len(matrix), dtype=np.float64)
        for start in range(0, len(matrix), 32):
            batch = matrix[start:start+32]
            rows = np.arange(len(batch))[:, None]
            positions = np.tile(self.roots, (len(batch), 1))
            while True:
                features = self.features[positions]
                active = features >= 0
                if not active.any():
                    break
                choose_left = batch[rows, np.maximum(features, 0)] <= self.thresholds[positions]
                positions = np.where(active,
                    np.where(choose_left, self.left[positions], self.right[positions]), positions)
            leaves = np.empty((len(batch), len(self.roots)+1), dtype=np.float64)
            leaves[:, 0] = 0.
            leaves[:, 1:] = self.values[positions]
            # Keep sequential tree addition exactly, including cancellation.
            result[start:start+len(batch)] = np.cumsum(leaves, axis=1)[:, -1]
        return result


@dataclass(frozen=True)
class NumericRanker:
    features: tuple[str, ...]
    _trees: tuple[_Tree, ...]

    @cached_property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

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

    def explain_pair(self, left: np.ndarray, right: np.ndarray) -> dict[str, Any]:
        """Account for a pair margin using actual paths, without fixed-weight claims."""
        matrix = np.asarray([left, right], dtype=np.float64)
        if matrix.shape != (2, len(self.features)):
            raise ValueError('one ranking feature vector per candidate required')
        scores = self.predict(matrix)
        margin = float(scores[0] - scores[1])
        if not np.isfinite(scores).all() or not math.isfinite(margin):
            raise ValueError('finite ranking scores and margin required')
        trees: list[dict[str, Any]] = []
        grouped: dict[str, list[float]] = {}
        for index, tree in enumerate(self._trees):
            left_leaf, left_path = tree.explain(matrix[0], self.features)
            right_leaf, right_path = tree.explain(matrix[1], self.features)
            delta = left_leaf - right_leaf
            divergence = next(({'feature': a['feature'], 'threshold': a['threshold'],
                                'left_value': a['value'], 'right_value': b['value'],
                                'left_branch': a['branch'], 'right_branch': b['branch']}
                               for a, b in zip(left_path, right_path)
                               if a['branch'] != b['branch']), None)
            if divergence is not None:
                grouped.setdefault(divergence['feature'], []).append(delta)
            trees.append({'tree_index': index, 'left_leaf': left_leaf, 'right_leaf': right_leaf,
                          'delta': delta, 'first_divergence': divergence,
                          'left_path': left_path, 'right_path': right_path})
        accounted = math.fsum(t['delta'] for t in trees)
        return {'model_fingerprint': self.fingerprint, 'left_score': float(scores[0]),
                'right_score': float(scores[1]), 'margin': margin, 'trees': trees,
                'branch_margin_by_feature': {name: math.fsum(values) for name, values in grouped.items()},
                'rounding_residual': margin - accounted,
                'attribution': 'Tree leaf differences grouped by first divergent split; '
                               'interaction accounting, not isolated causal feature effects or SHAP.'}

    @cached_property
    def _small_batch(self) -> _ArrayForest:
        return _ArrayForest.compile(self._trees)

    def predict(self, matrix: np.ndarray) -> np.ndarray:
        matrix = np.asarray(matrix, dtype=np.float64)
        if matrix.ndim != 2 or matrix.shape[1] != len(self.features):
            raise ValueError('ranking feature schema mismatch')
        if not np.isfinite(matrix).all():
            raise ValueError('finite ranking features required')
        if 0 < len(matrix) <= 128:
            return self._small_batch.predict(matrix)
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
