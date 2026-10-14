from dataclasses import replace

import numpy as np
import pytest

from ken.retrieval.dense import DenseView
from ken.retrieval.embedding_store import VectorView
from ken.retrieval.model import Span
from tests.retrieval.test_ranking import candidate


def reference(passages, ids, matrix, query, limit):
    scores = matrix @ (query / np.linalg.norm(query))
    groups = {}
    for i in np.argsort(-scores, kind='stable'):
        p = passages[ids[int(i)]]
        groups.setdefault(p.entity, []).append((float(scores[i]), p))
    return [(entity, pairs[:4]) for entity,pairs in list(groups.items())[:limit]]


def test_grouped_dense_view_preserves_reference_owner_scores_and_late_evidence():
    rng = np.random.default_rng(42)
    passages = {}
    for i in range(600):
        p = candidate('function_'+str(i % 17), str(i)).passages[0]
        passages[100+i] = replace(p, span=Span(i+1,i+1))
    ids = tuple(passages)
    matrix = rng.normal(size=(len(ids), 8)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix[10:15] = matrix[9]  # deterministic ties
    view = DenseView(passages, VectorView(ids, matrix, 'revision'))
    for query in (rng.normal(size=8).astype(np.float32), matrix[9]):
        expected = reference(passages, ids, matrix, query, 6)
        actual = view.search(query, 'behavior', 6)
        assert [c.entity for c in actual] == [e for e,p in expected]
        for result, (_, evidence) in zip(actual, expected, strict=True):
            assert result.signals['cosine_behavior'] == evidence[0][0]
            assert [(p.span,p.signals['cosine_behavior']) for p in result.passages] == [(p.span,s) for s,p in evidence]
    assert not view.labels.flags.writeable


def test_dense_view_validates_query_and_covers_fewer_owners_than_limit():
    p = candidate('one', 'body').passages[0]
    view = DenseView({1:p}, VectorView((1,), np.array([[1.,0.]], dtype=np.float32), 'r'))
    assert len(view.search(np.array([1.,0.]), 'identity', 100)) == 1
    with pytest.raises(ValueError, match='invalid'):
        view.search(np.array([0.,0.]), 'identity', 100)
    with pytest.raises(ValueError, match='dimension'):
        view.search(np.array([1.]), 'identity', 100)
