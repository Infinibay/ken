"""Development-only literal query facets and bounded candidate proposals."""
from __future__ import annotations

import re
from dataclasses import replace

from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, EntityKey, SearchRequest, merge_spans

_ATOMS = re.compile(r'''`[^`]*`|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\S+''')


def facet_queries(request: SearchRequest, *, width: int = 8, max_facets: int = 6) -> list[str]:
    """Keep the full query and quote-preserving literal windows; never rewrite text."""
    if width <= 0 or max_facets <= 0:
        raise ValueError('positive query budgets required')
    intent = interpret(request)
    if intent.identity or (intent.identifiers and len(request.query.split()) == 1):
        return [request.query]
    atoms = list(_ATOMS.finditer(request.query))
    if len(atoms) <= width:
        return [request.query]
    last = len(atoms)-width
    starts = list(range(0,last+1,max(1,width//2)))
    if starts[-1] != last:
        starts.append(last)
    if len(starts) > max_facets:
        positions = [round(i*(len(starts)-1)/(max_facets-1)) for i in range(max_facets)] if max_facets>1 else [0]
        starts = [starts[i] for i in positions]
    return list(dict.fromkeys([request.query, *[request.query[atoms[i].start():atoms[i+width-1].end()] for i in starts]]))


def combine_proposals(pools: list[list[Candidate]], *, limit: int = 100,
                      primary_quota: int = 50, rrf_k: int = 60) -> list[Candidate]:
    """Reserve primary coverage; divide expansion weight across correlated facets."""
    if not pools or limit <= 0 or not 0 <= primary_quota <= limit or rrf_k <= 0:
        raise ValueError('valid proposal budgets and a primary pool required')
    if len(pools) == 1:
        return list(pools[0][:limit])
    weights = [.5, *[.5/(len(pools)-1)]*(len(pools)-1)]
    merged: dict[EntityKey,Candidate] = {}
    for qi,(pool,weight) in enumerate(zip(pools,weights,strict=True)):
        seen = set()
        for rank,c in enumerate(pool,1):
            if c.entity in seen:
                continue
            seen.add(c.entity)
            if c.entity not in merged:
                merged[c.entity] = Candidate(c.entity,[],{'rrf':0.},c.owned_regions)
            combined = merged[c.entity]
            hashes = {p.source_hash for p in (*combined.passages, *c.passages)}
            if len(hashes) != 1 or not c.passages:
                raise ValueError('mixed or missing source generations in proposal union')
            contribution = weight/(rrf_k+rank)
            combined.signals[f'proposal_{qi}'] = contribution
            combined.signals['rrf'] += contribution
            combined.signals['exact'] = max(c.signals.get('exact',0.),combined.signals.get('exact',0.))
            existing = {p.span for p in combined.passages}
            for p in c.passages:
                if p.span not in existing:
                    combined.passages.append(replace(p,signals={**p.signals,'proposal_query':float(qi)}))
                    existing.add(p.span)
            combined.owned_regions = merge_spans([*combined.owned_regions,*c.owned_regions])
    order = sorted(merged,key=lambda e:(-merged[e].signals.get('exact',0),-merged[e].signals['rrf'],e.path,
                                       min(p.span.start_line for p in merged[e].passages)))
    reserved = list(dict.fromkeys(c.entity for c in pools[0]))[:primary_quota]
    # Exact identities remain eligible even if a malformed caller pool placed
    # them after the primary quota. Normal unique-name lookup bypasses expansion.
    reserved = list(dict.fromkeys([*[e for e in order if merged[e].signals.get('exact')],*reserved]))[:limit]
    chosen = set((reserved+[e for e in order if e not in reserved])[:limit])
    return [merged[e] for e in order if e in chosen]
