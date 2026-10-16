"""Request-local observations of actual numeric ranking, with opt-in export."""
from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
import hashlib
from typing import Any
from uuid import uuid4

import numpy as np

from ken.retrieval.model import Candidate, CodeMatch, EntityKey
from ken.retrieval.numeric_ranker import NumericRanker


class RankingTrace:
    """Retain feature inputs and ordering decisions, without running retrieval."""

    def __init__(self, *, request_id: str | None = None):
        self.request_id = request_id or str(uuid4())
        self._data: dict[str, Any] | None = None
        self._model: NumericRanker | None = None
        self._values: np.ndarray | None = None
        self._index: dict[EntityKey, int] = {}
        self._query: str | None = None
        self._expanded: str | None = None
        self._attempt = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any], model: NumericRanker) -> RankingTrace:
        """Restore an observation only if scores and ordering reproduce exactly."""
        if (data['schema'] != 1 or data['model_fingerprint'] != model.fingerprint
                or data['feature_names'] != list(model.features)):
            raise ValueError('ranking trace model or feature schema mismatch')
        owners = data['owners']
        if ([o['proposal_index'] for o in owners] != list(range(len(owners)))
                or sorted(o['rank'] for o in owners) != list(range(1, len(owners) + 1))):
            raise ValueError('ranking trace proposal/final order is invalid')
        index = {EntityKey(path=o['path'], **o['entity']): i for i, o in enumerate(owners)}
        if len(index) != len(owners):
            raise ValueError('ranking trace contains duplicate owners')
        if data['policy'] == 'unique_exact':
            if (len(owners) != 1 or not owners[0]['signals'].get('exact')
                    or owners[0]['feature_values'] is not None):
                raise ValueError('ranking trace exact bypass is invalid')
            values = None
        else:
            if data['policy'] != 'exact_priority_then_model_score_then_proposal_order':
                raise ValueError('unknown ranking trace order policy')
            values = np.asarray([o['feature_values'] for o in owners], dtype=np.float64).reshape(
                len(owners), len(model.features))
            scores = np.array([o['score'] for o in owners], dtype=np.float64)
            if not np.array_equal(model.predict(values), scores):
                raise ValueError('ranking trace scores do not reproduce')
            order = sorted(range(len(owners)), key=lambda i: (
                -owners[i]['signals'].get('exact', 0), -owners[i]['score'], i))
            if [owners[i]['rank'] for i in order] != list(range(1, len(owners) + 1)):
                raise ValueError('ranking trace final order does not reproduce')
        result = cls(request_id=data['request_id'])
        fields = ('schema', 'request_id', 'attempt', 'entry_point', 'model_fingerprint',
                  'feature_version', 'evidence_version', 'policy', 'feature_names',
                  'owners', 'query_sha256', 'expanded_query_sha256')
        result._data = deepcopy({name: data[name] for name in fields})
        result._attempt, result._index = data['attempt'], index
        result._values, result._model = values, model if values is not None else None
        for name, attribute, pin in (('query', '_query', 'query_sha256'),
                                     ('expanded_query', '_expanded', 'expanded_query_sha256')):
            if name in data:
                if hashlib.sha256(data[name].encode()).hexdigest() != data[pin]:
                    raise ValueError('ranking trace query hash does not match')
                setattr(result, attribute, data[name])
        return result

    def record(self, *, model: NumericRanker, query: str, expanded: str,
               candidates: Sequence[Candidate], matches: Sequence[CodeMatch],
               values: np.ndarray | None, feature_version: int, evidence_version: int,
               policy: str = 'exact_priority_then_model_score_then_proposal_order') -> None:
        """Observe one completed ranking; replace a prior attempt's snapshot."""
        self._attempt += 1
        self._query, self._expanded = query, expanded
        self._model = model if values is not None else None
        self._values = np.array(values, dtype=np.float64, copy=True) if values is not None else None
        self._index = {candidate.entity: index for index, candidate in enumerate(candidates)}
        ranked = {match.entity: (rank, match) for rank, match in enumerate(matches, 1)}
        owners = []
        for index, candidate in enumerate(candidates):
            rank, match = ranked[candidate.entity]
            owners.append({'path': candidate.entity.path, 'entity': candidate.entity.to_dict(),
                           'proposal_index': index, 'rank': rank, 'score': match.score,
                           'source_hash': match.source_hash, 'signals': deepcopy(candidate.signals),
                           'feature_values': self._values[index].tolist() if self._values is not None else None})
        self._data = {'schema': 1, 'request_id': self.request_id, 'attempt': self._attempt,
                      'entry_point': 'retrieval.owner_ranking', 'model_fingerprint': model.fingerprint,
                      'feature_version': feature_version, 'evidence_version': evidence_version,
                      'policy': policy, 'feature_names': list(model.features), 'owners': owners,
                      'query_sha256': hashlib.sha256(query.encode()).hexdigest(),
                      'expanded_query_sha256': hashlib.sha256(expanded.encode()).hexdigest()}

    def to_dict(self, *, include_query: bool = False) -> dict[str, Any]:
        if self._data is None:
            raise ValueError('ranking trace has no observation')
        result = deepcopy(self._data)
        if include_query:
            if self._query is not None:
                result['query'] = self._query
            if self._expanded is not None:
                result['expanded_query'] = self._expanded
        return result

    def compare(self, left: EntityKey, right: EntityKey) -> dict[str, Any]:
        if self._data is None or self._model is None or self._values is None:
            raise ValueError('no numeric feature observation is available for comparison')
        left_index, right_index = self._index[left], self._index[right]
        owners = self._data['owners']
        a, b = owners[left_index], owners[right_index]
        if a['signals'].get('exact', 0) != b['signals'].get('exact', 0):
            reason = 'exact_identity_priority'
        elif a['score'] != b['score']:
            reason = 'numeric_model_score'
        else:
            reason = 'stable_proposal_order'
        return {'request_id': self.request_id, 'ordering_reason': reason,
                'left': deepcopy(a), 'right': deepcopy(b),
                'differing_features': [
                    {'feature': name, 'left': float(x), 'right': float(y)}
                    for name, x, y in zip(self._model.features, self._values[left_index],
                                          self._values[right_index], strict=True) if x != y],
                'numeric': self._model.explain_pair(self._values[left_index], self._values[right_index])}
