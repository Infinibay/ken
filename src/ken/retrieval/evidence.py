"""Select a faithful source window within the responsibility of a ranked owner."""
from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from itertools import combinations
from pathlib import Path

import numpy as np

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, CodeMatch, Passage, SearchRequest, Span, merge_spans
from ken.retrieval.ranking import RelevanceJudge, candidate_document
from ken.retrieval.result_selection import displayed_matches


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


def entity_extent(match: CodeMatch) -> Span:
    """Enclose known owner metadata, without authorizing evidence in its gaps."""
    if not match.evidence or any(p.entity != match.entity or p.source_hash != match.source_hash
                                 for p in match.evidence):
        raise ValueError("entity extent requires one source owner and version")
    spans = [s for p in match.evidence for s in (p.entity_span, p.span)]
    spans.extend(match.owned_regions)
    return Span(min(s.start_line for s in spans), max(s.end_line for s in spans))


def source_bounds(match: CodeMatch, passage: Passage, line_count: int, *,
                  implementation: bool) -> Span:
    lower, upper = passage.entity_span.start_line, passage.entity_span.end_line
    if match.entity.qualname is None:
        lower, upper = 1, line_count
    # Adjacent chunks merge into one owned region. Nested callable bodies are
    # gaps, including within functions: expanding across them borrows evidence.
    regions = match.owned_regions or merge_spans(p.span for p in match.evidence if p.entity == match.entity)
    if regions:
        region = next((r for r in regions
                       if r.start_line <= passage.span.start_line <= r.end_line), passage.span)
        lower, upper = region.start_line, region.end_line
    if implementation and upper - lower + 1 > 40:
        lower = min(upper, max(lower, passage.implementation_start_line or lower))
    return Span(lower, upper)


def complete_owned_context(match: CodeMatch, root: Path) -> CodeMatch:
    """Expose a complete small responsibility while retaining every owner gap."""
    if not match.owned_regions:
        return match
    entity_extent(match)
    lines = verified_lines(root, match)
    template = match.evidence[0]
    regions = merge_spans(source_bounds(match, replace(template, span=region), len(lines),
        implementation=True) for region in match.owned_regions)
    if (not regions or len(regions) > 3
            or sum(r.end_line-r.start_line+1 for r in regions) > 40):
        return match
    if any(r.end_line > len(lines) for r in regions):
        raise ValueError('owned source region exceeds current source')
    evidence = [replace(template, span=region,
        fields={**template.fields, 'body': '\n'.join(lines[region.start_line-1:region.end_line])},
        signals={**template.signals, 'selected_window': 1.}) for region in regions]
    return replace(match, evidence=evidence)


def complete_evidence(matches: list[CodeMatch], root: Path, request: SearchRequest) -> list[CodeMatch]:
    intent = interpret(request)
    if intent.identity or intent.purpose == 'documentation':
        return matches
    result = list(matches)
    for index, match in displayed_matches(matches, request):
        if match.signals.get('exact'):
            continue
        try:
            result[index] = complete_owned_context(match, root)
        except (OSError, ValueError, UnicodeError):
            continue  # Presentation owns reporting stale source and retry policy.
    return result


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
    return sorted(proposals.values(), key=lambda p: (-_utility(match, (p,)), p.span.start_line))[:limit]


def _utility(match: CodeMatch, fragments: tuple[Passage, ...]) -> float:
    peak = max(p.signals.get("joint_evidence", 0.) for p in match.evidence)
    # Fragments are nonoverlapping; a retrieval unit contributes its overlap
    # fraction, never one additional vote per duplicate passage.
    return sum(math.exp(max(-40., p.signals.get("joint_evidence", 0.) - peak)) * sum(max(0,
               min(p.span.end_line, w.span.end_line) - max(p.span.start_line, w.span.start_line) + 1)
               for w in fragments) / (p.span.end_line - p.span.start_line + 1)
               for p in {p.span: p for p in match.evidence}.values())


def _bundles(match: CodeMatch, lines: list[str], *, purpose: str, limit: int,
             max_fragments: int) -> list[tuple[Passage, ...]]:
    singles = _windows(match, lines, purpose=purpose, limit=limit)
    proposals: dict[tuple[Span, ...], tuple[Passage, ...]] = {(p.span,): (p,) for p in singles}
    distinct = {p.span: p for p in match.evidence}
    strongest = sorted(distinct.values(), key=lambda p: (
        -p.signals.get("joint_evidence", 0.), p.span.start_line))[:4]
    for count in range(2, min(max_fragments, len(strongest)) + 1):
        for group in combinations(strongest, count):
            fragments = []
            for index, p in enumerate(group):
                bounds = source_bounds(match, p, len(lines), implementation=purpose != "documentation")
                width = min(40 // count + int(index < 40 % count), bounds.end_line - bounds.start_line + 1)
                center = (p.span.start_line + p.span.end_line) // 2
                start = max(bounds.start_line, min(center - width // 2, bounds.end_line - width + 1))
                span = Span(start, start + width - 1)
                fragments.append(replace(p, span=span,
                    fields={**p.fields, "body": "\n".join(lines[span.start_line-1:span.end_line])}))
            fragments.sort(key=lambda p: p.span.start_line)
            if any(a.span.end_line >= b.span.start_line for a, b in zip(fragments, fragments[1:])):
                continue
            proposals.setdefault(tuple(p.span for p in fragments), tuple(fragments))
    ordered = sorted(proposals.values(), key=lambda bundle: (-_utility(match, bundle),
                     len(bundle), tuple(p.span for p in bundle)))
    # Preserve contiguous options: distributing every budget across fragments
    # can cut a long, decisive branch even when a full window covers it.
    reserved = [(p,) for p in singles[:min(2, limit)]]
    return (reserved + [bundle for bundle in ordered if bundle not in reserved])[:limit]


def refine_evidence(matches: list[CodeMatch], root: Path, request: SearchRequest, *,
                    judge: RelevanceJudge, limit: int = 1, max_windows: int = 6,
                    max_fragments: int = 3) -> list[CodeMatch]:
    if limit <= 0 or max_windows <= 0 or not 1 <= max_fragments <= 4:
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
        bundles = _bundles(match, lines, purpose=intent.purpose, limit=max_windows,
                            max_fragments=max_fragments)
        if not bundles:
            continue
        scores = np.asarray(judge.score(request.query, [candidate_document(
            Candidate(match.entity, list(bundle)), purpose=intent.purpose) for bundle in bundles],
            purpose=intent.purpose), dtype=np.float64)
        if scores.shape != (len(bundles),) or not np.isfinite(scores).all():
            raise ValueError("evidence selector must return one finite score per source window")
        best = max(range(len(bundles)), key=lambda i: (scores[i], -len(bundles[i])))
        evidence = [replace(p, signals={**p.signals, "selected_window": 1.,
                    "window_relevance": float(scores[best])}) for p in bundles[best]]
        result[index] = replace(match, evidence=evidence,
            signals={**match.signals, "window_relevance": float(scores[best])})
    return result
