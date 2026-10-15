"""Cover distinct query cues with faithful, bounded fragments of one owner."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from itertools import combinations
from pathlib import Path

from ken.retrieval.evidence import source_bounds, verified_lines
from ken.retrieval.intent import interpret
from ken.retrieval.model import CodeMatch, Passage, SearchRequest, Span
from ken.retrieval.tokenization import code_tokens


def _window_masks(regions: tuple[Span, ...], masks: dict[int, int], width: int,
                  limit: int = 24) -> list[tuple[Span, int]]:
    proposals: dict[Span, int] = {}
    for region in regions:
        size = min(width, region.end_line-region.start_line+1)
        starts = {region.start_line, region.end_line-size+1}
        for line, mask in masks.items():
            if mask and region.start_line <= line <= region.end_line:
                starts.update(max(region.start_line, min(start, region.end_line-size+1))
                              for start in (line-size+1, line-size//2, line))
        for start in starts:
            span = Span(start, start+size-1)
            covered = 0
            for line in range(span.start_line, span.end_line+1):
                covered |= masks.get(line, 0)
            proposals[span] = covered
    ordered = sorted(proposals.items(), key=lambda item: (-item[1].bit_count(), item[0]))
    # Retain windows that add a distinct cue before filling redundant context.
    selected: list[tuple[Span, int]] = []
    covered = 0
    for item in ordered:
        if item[1] & ~covered:
            selected.append(item); covered |= item[1]
        if len(selected) == limit:
            break
    return (selected+[item for item in ordered if item not in selected])[:limit]


def _select(match: CodeMatch, lines: list[str], query_terms: set[str], *,
            stem_words: Callable[[list[str]], list[str]], purpose: str) -> list[Passage] | None:
    regions = tuple(sorted({source_bounds(match,p,len(lines),implementation=purpose!='documentation')
                            for p in match.evidence}))
    words_by_line = {line: set(code_tokens(lines[line-1])) for r in regions
                     for line in range(r.start_line,r.end_line+1)}
    vocabulary = sorted(query_terms | {w for words in words_by_line.values() for w in words})
    stems = dict(zip(vocabulary,stem_words(vocabulary),strict=True))
    terms = {word:1<<i for i,word in enumerate(sorted({stems[w] for w in query_terms}))}
    masks: dict[int,int] = {}
    for line, words in words_by_line.items():
        mask = 0
        for word in words:
            mask |= terms.get(stems[word],0)
        masks[line] = mask
    best_key: tuple[int,int,tuple[int,...]] = (0,0,())
    best: tuple[Span,...] = ()
    for count in (1,2,3):
        windows = _window_masks(regions,masks,40//count)
        for bundle in combinations(windows,count):
            spans = tuple(sorted(span for span,_ in bundle))
            if any(a.end_line >= b.start_line for a,b in zip(spans,spans[1:])):
                continue
            covered = 0
            for _,mask in bundle:
                covered |= mask
            # A repeated cue adds no vote. Prefer contiguous context when a
            # split offers no additional coverage of the query.
            key = (covered.bit_count(),-count,tuple(-s.start_line for s in spans))
            if key > best_key:
                best_key,best = key,spans
    if not best or best_key[0] == 0:
        return None
    result = []
    for span in best:
        template = next((p for p in match.evidence if
            source_bounds(match,p,len(lines),implementation=purpose!='documentation').start_line <= span.start_line
            and source_bounds(match,p,len(lines),implementation=purpose!='documentation').end_line >= span.end_line))
        result.append(replace(template,span=span,
            fields={**template.fields,'body':'\n'.join(lines[span.start_line-1:span.end_line])},
            signals={**template.signals,'selected_window':1.}))
    return result


def refine_source_evidence(matches: list[CodeMatch], root: Path, request: SearchRequest, *,
                           query: str, stem_words: Callable[[list[str]], list[str]]) -> list[CodeMatch]:
    intent = interpret(request)
    if intent.identity:
        return matches
    result = list(matches)
    terms = set(code_tokens(query))
    for index,match in enumerate(matches[:request.limit]):
        if match.signals.get('exact'):
            continue
        try:
            lines = verified_lines(root,match)
        except (OSError,ValueError,UnicodeError):
            continue  # Presentation reports stale bytes and owns retry policy.
        evidence = _select(match,lines,terms,stem_words=stem_words,purpose=intent.purpose)
        if evidence:
            result[index] = replace(match,evidence=evidence)
    return result
