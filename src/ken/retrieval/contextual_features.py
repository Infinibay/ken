"""Summarize original and expanded contextual evidence within one proposal pool."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ken.retrieval.evidence_features import FeatureMatrix
from ken.retrieval.model import Candidate
from ken.retrieval.source_views import SOURCE_VIEW_NAMES

CONTEXTUAL_FEATURES = tuple(f'code_{query}_{stat}'
    for query in ('original', 'expanded')
    for stat in ('raw', 'to_max', 'range_relative', 'reciprocal_rank'))
SOURCE_VIEW_FEATURES = tuple(f'view_{view}_{query}_{stat}'
    for view in SOURCE_VIEW_NAMES for query in ('original', 'expanded')
    for stat in ('raw', 'to_max', 'range_relative', 'reciprocal_rank'))


def contextual_features(candidates: Sequence[Candidate], *, source_views: bool = False) -> FeatureMatrix:
    """Missing evidence is a profile error; a measured zero remains a real score."""
    features = (*CONTEXTUAL_FEATURES, *SOURCE_VIEW_FEATURES) if source_views else CONTEXTUAL_FEATURES
    if not candidates:
        return FeatureMatrix(features, np.empty((0, len(features))))
    columns: list[np.ndarray] = []
    signals = ['cosine_code_original', 'cosine_code_expanded']
    if source_views:
        signals.extend(f'cosine_view_{view}_{query}' for view in SOURCE_VIEW_NAMES
                       for query in ('original', 'expanded'))
    for name in signals:
        if any(name not in c.signals for c in candidates):
            raise ValueError('contextual ranking requires scores for every proposed owner')
        values = np.asarray([c.signals[name] for c in candidates], dtype=np.float64)
        if not np.isfinite(values).all():
            raise ValueError('contextual scores must be finite')
        ranks = np.empty(len(values))
        ranks[np.argsort(-values, kind='stable')] = np.arange(1, len(values)+1)
        columns.extend((values, values-values.max(),
            (values-values.min())/max(1e-9, float(np.ptp(values))), 1/ranks))
    return FeatureMatrix(features, np.stack(columns, axis=1))
