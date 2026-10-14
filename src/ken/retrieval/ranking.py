"""Order owners using candidate evidence and optional joint query/code relevance."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import numpy as np

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, CodeMatch, EntityKey, Passage, SearchRequest
from ken.retrieval.linear import LinearRanker, candidate_features


class RelevanceJudge(Protocol):
    def score(self, query: str, documents: list[str], *, purpose: str) -> Sequence[float] | np.ndarray: ...


def candidate_document(candidate: Candidate, *, purpose: str = "implementation") -> str:
    first = candidate.passages[0]
    ordered = sorted(candidate.passages, key=lambda p: (
        -(p.implementation_start_line is None or p.span.end_line >= p.implementation_start_line),
        -p.signals.get("cosine_behavior", -1), p.span.start_line))
    # Repeated chunks carry no independent vote or additional information.
    bodies = []
    for passage in ordered:
        body = passage.fields["body"]
        if purpose in ("implementation", "tests", "usage") and passage.implementation_start_line is not None:
            offset = max(0, passage.implementation_start_line - passage.span.start_line)
            body = "\n".join(body.split("\n")[offset:])
        if body.strip() and body not in bodies:
            bodies.append(body)
    documentation = (first.fields.get("documentation", "")[:600]
                     if purpose in ("identity", "documentation") else "")
    return "\n".join((candidate.entity.path, first.role,
        first.fields.get("identity", ""), first.fields.get("signature", ""),
        "Source:\n" + ("\n\n".join(bodies[:4]) or "<no owned executable source>"),
        "Documentation:\n" + documentation))


def rank_candidates(request: SearchRequest, candidates: list[Candidate], *,
                    judge: RelevanceJudge | None = None, rerank_limit: int = 40,
                    linear: LinearRanker | None = None, rank_unit: str = "entity") -> list[CodeMatch]:
    scores_by_entity = {c.entity: linear.score(candidate_features(request, c))
                        if linear else c.signals.get("rrf", 0.0) for c in candidates}
    ordered = sorted(candidates, key=lambda c: (
        -c.signals.get("exact", 0), -scores_by_entity[c.entity],
        c.entity.path, min(p.span.start_line for p in c.passages)))
    if judge is None or (len(ordered) == 1 and ordered[0].signals.get("exact")):
        return [CodeMatch(c.entity, scores_by_entity[c.entity], c.passages,
                          c.passages[0].source_hash, {**c.signals,
                          **({"linear_relevance": scores_by_entity[c.entity]} if linear else {})},
                          c.owned_regions) for c in ordered]
    selected = ordered[:rerank_limit]
    intent = interpret(request)
    purpose = "identity" if intent.identity else intent.purpose
    if rank_unit == "passage":
        return _rank_passages(request, selected, judge, purpose)
    if rank_unit != "entity":
        raise ValueError("unknown joint ranking unit")
    scores = np.asarray(judge.score(request.query, [candidate_document(c, purpose=purpose) for c in selected],
                                   purpose=purpose), dtype=np.float64)
    if scores.shape != (len(selected),) or not np.isfinite(scores).all():
        raise ValueError("joint ranker must return one finite score per candidate")
    matches = [CodeMatch(c.entity, float(score), c.passages, c.passages[0].source_hash,
                         {**c.signals, "joint_relevance": float(score)}, c.owned_regions)
               for c, score in zip(selected, scores, strict=True)]
    return sorted(matches, key=lambda m: (-m.signals.get("exact", 0), -m.score,
                                          m.entity.path, m.evidence[0].span.start_line))


def _rank_passages(request: SearchRequest, candidates: list[Candidate],
                    judge: RelevanceJudge, purpose: str) -> list[CodeMatch]:
    units: list[tuple[Candidate, Passage]] = []
    for candidate in candidates:
        unique = {p.span: p for p in candidate.passages}
        passages = list(unique.values())
        executable = [p for p in passages if p.implementation_start_line is None
                      or p.span.end_line >= p.implementation_start_line]
        if purpose not in ("identity", "documentation"):
            passages = executable or passages[:1]
        units.extend((candidate, p) for p in passages)
    documents = [candidate_document(Candidate(c.entity, [p], c.signals), purpose=purpose)
                 for c, p in units]
    scores = np.asarray(judge.score(request.query, documents, purpose=purpose), dtype=np.float64)
    if scores.shape != (len(units),) or not np.isfinite(scores).all():
        raise ValueError("joint ranker must return one finite score per evidence unit")
    grouped: dict[EntityKey, list[Passage]] = {}
    for (candidate, passage), score in zip(units, scores, strict=True):
        grouped.setdefault(candidate.entity, []).append(replace(
            passage, signals={**passage.signals, "joint_evidence": float(score)}))
    matches = []
    for candidate in candidates:
        evidence = grouped[candidate.entity]
        score = max(p.signals["joint_evidence"] for p in evidence)
        matches.append(CodeMatch(candidate.entity, score, evidence, evidence[0].source_hash,
            {**candidate.signals, "joint_relevance": score, "joint_units": float(len(evidence))},
            candidate.owned_regions))
    return sorted(matches, key=lambda m: (-m.signals.get("exact", 0), -m.score,
                                         m.entity.path, m.evidence[0].span.start_line))
