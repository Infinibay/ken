"""Propose bounded source answers before choosing which answer to expose."""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import replace
from itertools import combinations

from ken.retrieval.evidence import source_bounds
from ken.retrieval.intent import interpret
from ken.retrieval.model import CodeMatch, Passage, SearchRequest, Span, merge_spans
from ken.retrieval.tokenization import code_tokens


def propose_windows(match: CodeMatch, lines: list[str], request: SearchRequest, *,
                    query: str, stem_words: Callable[[list[str]], list[str]],
                    statements: Sequence[Span] = (), limit: int = 12
                    ) -> list[tuple[Passage, ...]]:
    """Source-only hypotheses; no relevance labels enter proposal selection.

    Complete statement windows, query-cue windows, region edges and disjoint
    bundles compete under explicit quotas. Every hypothesis fits40 source lines
    and preserves the original owner gaps. The caller verifies source bytes.
    """
    if limit <= 0 or not match.evidence:
        raise ValueError('source evidence and a positive hypothesis budget required')
    if any(p.entity != match.entity or p.source_hash != match.source_hash for p in match.evidence):
        raise ValueError('window proposals require one source owner and version')
    intent = interpret(request)
    regions = merge_spans(source_bounds(match, p, len(lines),
        implementation=intent.purpose != 'documentation' and not intent.identity) for p in match.evidence)
    if any(r.end_line > len(lines) for r in regions):
        raise ValueError('window region outside current source')

    def materialize(spans: tuple[Span, ...]) -> tuple[Passage, ...]:
        return tuple(replace(next(p for p in match.evidence if
            source_bounds(match, p, len(lines), implementation=False).start_line <= s.start_line
            <= source_bounds(match, p, len(lines), implementation=False).end_line), span=s,
            fields={**match.evidence[0].fields, 'body': '\n'.join(lines[s.start_line-1:s.end_line])},
            signals={'selected_window': 1.}) for s in spans)

    if intent.identity:
        region = regions[0]
        return [materialize((Span(region.start_line, min(region.end_line, region.start_line+39)),))]
    words = {i: set(code_tokens(lines[i-1])) for r in regions for i in range(r.start_line, r.end_line+1)}
    query_words = list(dict.fromkeys(code_tokens(query)))[:128]
    vocabulary = sorted(set(query_words) | {w for ws in words.values() for w in ws})
    stems = dict(zip(vocabulary, stem_words(vocabulary), strict=True))
    terms = sorted({stems[w] for w in query_words})
    bits = {term: 1 << i for i, term in enumerate(terms)}
    masks = {line: sum(bits[t] for t in {stems[w] for w in ws} if t in bits)
             for line, ws in words.items()}
    weights = {bits[t]: math.log1p(len(words)/(1+sum(bool(mask & bits[t]) for mask in masks.values())))
               for t in terms}
    mask_cache: dict[Span, int] = {}

    def mask(span: Span) -> int:
        if span not in mask_cache:
            value = 0
            for i in range(span.start_line, span.end_line+1):
                value |= masks[i]
            mask_cache[span] = value
        return mask_cache[span]

    def score(spans: tuple[Span, ...]) -> tuple[float, int, int, tuple[tuple[int, int], ...]]:
        value = 0
        for span in spans:
            value |= mask(span)
        return (sum(weight for bit, weight in weights.items() if bit & value),
                -len(spans), sum(s.end_line-s.start_line+1 for s in spans),
                tuple((-s.start_line, -s.end_line) for s in spans))

    edges: list[tuple[Span, ...]] = []
    grid: list[tuple[Span, ...]] = []
    structural: list[tuple[Span, ...]] = []
    half: list[tuple[Span, ...]] = []
    for region in regions:
        width = min(40, region.end_line-region.start_line+1)
        edges.extend(((Span(region.start_line, region.start_line+width-1),),
                      (Span(region.end_line-width+1, region.end_line),)))
        grid.extend((Span(i, i+width-1),) for i in range(region.start_line, region.end_line-width+2))
        owned_statements = sorted(s for s in statements if region.start_line <= s.start_line
                                  <= s.end_line <= region.end_line and s.end_line-s.start_line < 40)
        for statement in owned_statements:
            start = max(region.start_line, min(statement.start_line-(width-(statement.end_line-statement.start_line+1))//2,
                                               region.end_line-width+1))
            structural.extend(((statement,), (Span(start, start+width-1),)))
        half_width = min(20, region.end_line-region.start_line+1)
        half.extend((Span(i, i+half_width-1),)
                    for i in range(region.start_line, region.end_line-half_width+2))

    selected: list[tuple[Span, ...]] = []

    def take(options: Sequence[tuple[Span, ...]], quota: int, *, diverse: bool = False) -> None:
        accepted = 0
        for item in sorted(set(options), key=score, reverse=True):
            if accepted >= quota or len(selected) >= limit:
                break
            if item in selected:
                continue
            if diverse and any(len(prior) == len(item) == 1 and
                max(0, min(prior[0].end_line, item[0].end_line)-max(prior[0].start_line, item[0].start_line)+1)
                > .75 * min(prior[0].end_line-prior[0].start_line+1, item[0].end_line-item[0].start_line+1)
                for prior in selected):
                continue
            selected.append(item)
            accepted += 1

    take(structural, min(4, max(0, limit-4)), diverse=True)
    take(grid, max(1, limit-4-len(selected)), diverse=True)
    take(edges, 2)
    # A small diverse shortlist bounds the cross product independently of the
    # number of lines in a long function. Hypotheses never overlap themselves.
    shortlisted: list[Span] = []
    for item in sorted(set(half), key=score, reverse=True):
        span = item[0]
        if all(abs(span.start_line-s.start_line) >= 10 for s in shortlisted):
            shortlisted.append(span)
        if len(shortlisted) == 8:
            break
    bundles = [tuple(sorted(pair)) for pair in combinations(shortlisted, 2)
               if pair[0].end_line < pair[1].start_line or pair[1].end_line < pair[0].start_line]
    take(bundles, 2)
    take([*structural, *grid, *edges, *bundles], limit-len(selected))
    return [materialize(item) for item in sorted(selected, key=score, reverse=True)]
