"""Choose query-balanced source-owner rank groups without held-repo examples."""
from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TrainingGroup:
    qid: str
    repo: str
    positive: int
    negatives: tuple[int, ...]


def training_groups(*, qids: np.ndarray, repos: np.ndarray, labels: np.ndarray,
                    indexes: np.ndarray, pair_scores: np.ndarray, held_out: str,
                    exact_ids: Set[str] = frozenset()) -> tuple[TrainingGroup, ...]:
    arrays = (qids, repos, labels, indexes, pair_scores)
    if (any(a.ndim != 1 or a.shape != qids.shape for a in arrays)
            or not len(qids) or held_out not in set(repos)
            or indexes.dtype.kind not in 'iu' or not np.isin(labels, (0, 1)).all()
            or not np.isfinite(pair_scores).all()):
        raise ValueError('bound finite binary relevance rows and a held repository required')
    result = []
    for qid in dict.fromkeys(map(str, qids)):
        rows = np.flatnonzero(qids == qid)
        repository = set(map(str, repos[rows]))
        if len(repository) != 1 or not np.array_equal(indexes[rows], np.arange(len(rows))):
            raise ValueError('query rows need one repository and original candidate order')
        repo = repository.pop()
        if repo == held_out or qid in exact_ids:
            continue
        positive = rows[labels[rows] == 1]
        negative = rows[labels[rows] == 0]
        if not len(positive) or not len(negative):
            continue
        # Include one proposal-order negative, then the strongest pretrained
        # mistakes. The teacher has never fitted any development references.
        hard = sorted(map(int, negative), key=lambda i: (-pair_scores[i], i))
        selected = list(dict.fromkeys((int(negative[0]), *hard)))[:4]
        result.append(TrainingGroup(qid, repo, int(positive[0]), tuple(selected)))
    return tuple(result)
