"""Auditable pairwise relevance, fitted only from independently judged preferences."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, SearchRequest
from ken.retrieval.tokenization import code_tokens

FEATURES = ("rrf", "cosine_identity", "cosine_behavior", "bm25f", "bm25_body",
    "bm25_documentation", "bm25_identity", "bm25_signature", "bm25_path", "role_match",
    "class", "module", "log_lines", "name_overlap", "body_overlap")


def candidate_features(request: SearchRequest, candidate: Candidate) -> dict[str, float]:
    features = {name: float(candidate.signals.get(name, 0)) for name in FEATURES[:9]}
    for name in FEATURES[3:9]:
        features[name] = math.log1p(max(0, features[name]))
    intent = interpret(request)
    role = candidate.passages[0].role
    expected = {"implementation": "definition", "tests": "test", "usage": "example",
                "documentation": "documentation"}[intent.purpose]
    query = set(code_tokens(request.query))
    name_tokens = set(code_tokens(candidate.entity.qualname or ""))
    features.update({
        "role_match": float(role == expected),
        "class": float(candidate.entity.kind == "class"),
        "module": float(candidate.entity.qualname is None),
        "log_lines": math.log1p(max(p.entity_span.end_line - p.entity_span.start_line + 1
                                   for p in candidate.passages)),
        "name_overlap": len(query & name_tokens) / max(1, len(query)),
        "body_overlap": max(len(query & set(code_tokens(p.fields["body"]))) / max(1, len(query))
                            for p in candidate.passages),
    })
    return features


@dataclass(frozen=True)
class Preference:
    group: str
    positive: Mapping[str, float]
    negative: Mapping[str, float]


@dataclass(frozen=True)
class LinearRanker:
    features: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    weights: tuple[float, ...]
    training_groups: tuple[str, ...]
    training_sha256: str
    regularization: float

    def __post_init__(self) -> None:
        if self.features != FEATURES or not all(len(v) == len(FEATURES)
                for v in (self.means, self.scales, self.weights)):
            raise ValueError("incompatible linear feature schema")
        if (not all(math.isfinite(v) for values in (self.means, self.scales, self.weights) for v in values)
                or min(self.scales) <= 0):
            raise ValueError("invalid linear normalization or weights")

    def explain(self, features: Mapping[str, float]) -> dict[str, float]:
        return {name: (features.get(name, 0) - mean) / scale * weight
                for name, mean, scale, weight in zip(
                    self.features, self.means, self.scales, self.weights, strict=True)}

    def score(self, features: Mapping[str, float]) -> float:
        return sum(self.explain(features).values())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> LinearRanker:
        return cls(**{**data, **{name: tuple(data[name]) for name in
            ("features", "means", "scales", "weights", "training_groups")}})


def fit_ranker(preferences: Sequence[Preference], *, validation_groups: set[str],
               regularization: float = .1) -> LinearRanker:
    if not preferences or not math.isfinite(regularization) or regularization <= 0:
        raise ValueError("judged preferences and positive finite regularization required")
    groups = {pair.group for pair in preferences}
    if groups & validation_groups:
        raise ValueError("training/validation repository overlap")
    positive = np.array([[p.positive.get(name, 0) for name in FEATURES] for p in preferences])
    negative = np.array([[p.negative.get(name, 0) for name in FEATURES] for p in preferences])
    if not np.isfinite(positive).all() or not np.isfinite(negative).all():
        raise ValueError("non-finite training features")
    # No validation row, even an unlabelled one, contributes to normalization.
    train = np.concatenate([positive, negative])
    means, scales = train.mean(axis=0), train.std(axis=0)
    scales = np.where(scales > 1e-8, scales, 1)
    differences = (positive - negative) / scales
    weights = np.zeros(len(FEATURES))
    lipschitz = np.linalg.norm(differences, ord=2) ** 2 / (4 * len(preferences)) + regularization
    for _ in range(1200):
        margins = differences @ weights
        gradient = -(differences.T @ np.exp(-np.logaddexp(0, margins))) / len(preferences) + regularization * weights
        weights -= gradient / lipschitz
        if np.linalg.norm(gradient) < 1e-8:
            break
    training_hash = hashlib.sha256(json.dumps([asdict(p) for p in preferences], sort_keys=True).encode()).hexdigest()
    return LinearRanker(FEATURES, tuple(means), tuple(scales), tuple(weights), tuple(sorted(groups)),
                        training_hash, regularization)
