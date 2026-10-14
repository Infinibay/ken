"""Select a faithful source window within the responsibility of a ranked owner."""
from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, CodeMatch, Passage, SearchRequest, Span
from ken.retrieval.ranking import RelevanceJudge, candidate_document


def verified_lines(root: Path, match: CodeMatch) -> list[str]:
    path = (root / match.entity.path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("source escapes project")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != match.source_hash:
        raise ValueError("source changed")
    lines = source.decode("utf-8").splitlines()
    if any(p.span.end_line > len(lines) for p in match.evidence):
        raise ValueError("invalid source range")
    return lines


def source_bounds(match: CodeMatch, passage: Passage, line_count: int, *,
                  implementation: bool) -> Span:
    lower, upper = passage.entity_span.start_line, passage.entity_span.end_line
    if match.entity.qualname is None:
        lower, upper = 1, line_count
    # Classes and module fragments cannot become relevant by borrowing a
    # member's implementation. Functions may expand across their own chunks.
    if match.entity.kind not in ("function", "method", "constructor") and match.owned_regions:
        region = next((r for r in match.owned_regions
                       if r.start_line <= passage.span.start_line <= r.end_line), passage.span)
        lower, upper = region.start_line, region.end_line
    if implementation and upper - lower + 1 > 40:
        lower = min(upper, max(lower, passage.implementation_start_line or lower))
    return Span(lower, upper)


def _windows(match: CodeMatch, lines: list[str], *, purpose: str, limit: int) -> list[Passage]:
    proposals: dict[Span, Passage] = {}
    for p in match.evidence:
        bounds = source_bounds(match, p, len(lines), implementation=purpose not in ("identity", "documentation"))
        width = min(40, bounds.end_line - bounds.start_line + 1)
        # Start/end alignments preserve adjacent branches and chunks. A center
        # alone can cut one of two jointly necessary statements.
        starts = (p.span.start_line, p.span.end_line - width + 1,
                  (p.span.start_line + p.span.end_line - width + 1) // 2)
        for start in starts:
            start = max(bounds.start_line, min(start, bounds.end_line - width + 1))
            span = Span(start, start + width - 1)
            proposals.setdefault(span, replace(p, span=span,
                fields={**p.fields, "body": "\n".join(lines[span.start_line-1:span.end_line])}))
    if not proposals:
        return []
    peak = max(p.signals.get("joint_evidence", 0.) for p in match.evidence)
    def utility(window: Passage) -> float:
        # A unit contributes its overlap fraction, not one vote per duplicate.
        return sum(math.exp(max(-40., p.signals.get("joint_evidence", 0.) - peak)) * max(0,
                   min(p.span.end_line, window.span.end_line) - max(p.span.start_line, window.span.start_line) + 1)
                   / (p.span.end_line - p.span.start_line + 1)
                   for p in {p.span: p for p in match.evidence}.values())
    return sorted(proposals.values(), key=lambda p: (-utility(p), p.span.start_line))[:limit]


def refine_evidence(matches: list[CodeMatch], root: Path, request: SearchRequest, *,
                    judge: RelevanceJudge, limit: int = 1, max_windows: int = 6) -> list[CodeMatch]:
    if limit <= 0 or max_windows <= 0:
        raise ValueError("positive evidence selection budgets required")
    intent = interpret(request)
    if intent.identity:
        return matches
    result = list(matches)
    for index, match in enumerate(matches[:limit]):
        if match.signals.get("exact"):
            continue
        try:
            lines = verified_lines(root, match)
        except (OSError, ValueError, UnicodeError):
            # Presentation owns reporting stale source and retry policy.
            continue
        windows = _windows(match, lines, purpose=intent.purpose, limit=max_windows)
        if not windows:
            continue
        scores = np.asarray(judge.score(request.query, [candidate_document(
            Candidate(match.entity, [p]), purpose=intent.purpose) for p in windows],
            purpose=intent.purpose), dtype=np.float64)
        if scores.shape != (len(windows),) or not np.isfinite(scores).all():
            raise ValueError("evidence selector must return one finite score per source window")
        best = int(np.argmax(scores))
        evidence = replace(windows[best], signals={**windows[best].signals,
                           "selected_window": 1., "window_relevance": float(scores[best])})
        result[index] = replace(match, evidence=[evidence],
            signals={**match.signals, "window_relevance": float(scores[best])})
    return result
