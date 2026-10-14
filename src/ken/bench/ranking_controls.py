"""Experimental ranking controls; never part of the production search profile."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace

import numpy as np

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, CodeMatch, SearchRequest
from ken.retrieval.tokenization import code_tokens

FEATURES = ("rrf", "cosine_identity", "cosine_behavior", "bm25f", "bm25_body",
    "bm25_documentation", "bm25_identity", "bm25_signature", "bm25_path", "role_match",
    "class", "module", "log_lines", "name_overlap", "body_overlap")
JOINT_FEATURES = ("joint_relevance", "joint_missing", "role_match", "class", "module", "log_lines")


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
        "joint_relevance": candidate.signals.get("joint_relevance", 0.),
        "joint_missing": float("joint_relevance" not in candidate.signals),
    })
    return features


def rank_linear(request: SearchRequest, candidates: list[Candidate],
                model: LinearRanker) -> list[CodeMatch]:
    matches = []
    for candidate in candidates:
        score = model.score(candidate_features(request, candidate))
        matches.append(CodeMatch(candidate.entity, score, candidate.passages,
            candidate.passages[0].source_hash,
            {**candidate.signals, "linear_relevance": score}, candidate.owned_regions))
    return _ordered(matches)


def calibrate(request: SearchRequest, matches: list[CodeMatch],
              model: LinearRanker) -> list[CodeMatch]:
    calibrated = []
    for match in matches:
        features = candidate_features(request, Candidate(match.entity, match.evidence, match.signals))
        score = model.score(features)
        calibrated.append(replace(match, score=score,
            signals={**match.signals, "calibrated_relevance": score}))
    return _ordered(calibrated)


def _ordered(matches: list[CodeMatch]) -> list[CodeMatch]:
    return sorted(matches, key=lambda m: (-m.signals.get("exact", 0), -m.score,
                                         m.entity.path, m.evidence[0].span.start_line))


def _requested_role(request: SearchRequest) -> str | None:
    intent = interpret(request)
    if intent.identity or intent.purpose not in ("implementation", "tests"):
        return None
    return "test" if intent.purpose == "tests" else "definition"


def prefer_requested_role(request: SearchRequest, matches: list[CodeMatch]) -> list[CodeMatch]:
    """A categorical purpose control; does not manufacture relevance scores."""
    expected = _requested_role(request)
    if expected is None:
        return list(matches)
    return sorted(matches, key=lambda m: (-m.signals.get("exact", 0),
        -int(m.evidence[0].role == expected), -m.score, m.entity.path, m.evidence[0].span.start_line))


def select_requested_role_candidates(request: SearchRequest, candidates: list[Candidate], *,
                                     limit: int) -> list[Candidate]:
    """Spend the declared neural budget on the requested evidence role first."""
    if limit <= 0:
        raise ValueError("positive candidate budget required")
    expected = _requested_role(request)
    return sorted(candidates, key=lambda c: (-c.signals.get("exact", 0),
        -int(expected is not None and c.passages[0].role == expected),
        -c.signals.get("rrf", 0), c.entity.path, min(p.span.start_line for p in c.passages)))[:limit]


@dataclass(frozen=True)
class Preference:
    group: str
    positive: Mapping[str, float]
    negative: Mapping[str, float]
    query_id: str = ""


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
        if self.features not in (FEATURES, JOINT_FEATURES) or not all(len(v) == len(self.features)
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
               regularization: float = .1, features: tuple[str, ...] = FEATURES) -> LinearRanker:
    if not preferences or not math.isfinite(regularization) or regularization <= 0:
        raise ValueError("judged preferences and positive finite regularization required")
    groups = {pair.group for pair in preferences}
    if groups & validation_groups:
        raise ValueError("training/validation repository overlap")
    if features not in (FEATURES, JOINT_FEATURES):
        raise ValueError("unknown ranking feature schema")
    positive = np.array([[p.positive.get(name, 0) for name in features] for p in preferences])
    negative = np.array([[p.negative.get(name, 0) for name in features] for p in preferences])
    if not np.isfinite(positive).all() or not np.isfinite(negative).all():
        raise ValueError("non-finite training features")
    # No validation row, even an unlabelled one, contributes to normalization.
    query_keys = [(p.group, p.query_id or str(i)) for i, p in enumerate(preferences)]
    counts = Counter(query_keys)
    sample_weights = np.array([1. / counts[key] for key in query_keys])
    sample_weights /= sample_weights.sum()
    train = np.concatenate([positive, negative])
    train_weights = np.concatenate([sample_weights, sample_weights]) / 2
    means = np.average(train, axis=0, weights=train_weights)
    scales = np.sqrt(np.average((train-means)**2, axis=0, weights=train_weights))
    scales = np.where(scales > 1e-8, scales, 1)
    differences = (positive - negative) / scales
    weights = np.zeros(len(features))
    lipschitz = np.linalg.norm(differences * np.sqrt(sample_weights[:, None]), ord=2) ** 2 / 4 + regularization
    for _ in range(1200):
        margins = differences @ weights
        gradient = -(differences.T @ (sample_weights * np.exp(-np.logaddexp(0, margins)))) + regularization * weights
        weights -= gradient / lipschitz
        if np.linalg.norm(gradient) < 1e-8:
            break
    training_hash = hashlib.sha256(json.dumps([asdict(p) for p in preferences], sort_keys=True).encode()).hexdigest()
    return LinearRanker(features, tuple(means), tuple(scales), tuple(weights), tuple(sorted(groups)),
                        training_hash, regularization)
