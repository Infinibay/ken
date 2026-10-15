"""Fuse owner proposals while retaining the measurements that proposed them."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from ken.retrieval.model import Candidate, EntityKey, merge_spans


def _max_signals(target: dict[str, float], source: Mapping[str, float]) -> None:
    for name, value in source.items():
        target[name] = max(value, target.get(name, float('-inf')))


def fuse_proposals(channels: Mapping[str, Sequence[Candidate]], *, limit: int,
                   rrf_k: int = 60) -> list[Candidate]:
    """One reciprocal-rank vote per channel and owner, then a shared owner cap.

    The caller registers each retrieval run once. Different query variants may
    produce correlated runs; reciprocal-rank fusion makes no statistical
    independence claim. Identical runs must not receive multiple registrations.
    Raw scores and source evidence remain available for later ranking.
    """
    if limit <= 0 or rrf_k <= 0:
        raise ValueError('positive proposal and reciprocal-rank budgets required')
    merged: dict[EntityKey, Candidate] = {}
    source_versions: dict[str, str] = {}
    for channel, candidates in channels.items():
        seen: set[EntityKey] = set()
        for candidate in candidates:
            if not candidate.passages:
                raise ValueError('proposal requires source evidence')
            for passage in candidate.passages:
                prior_hash = source_versions.setdefault(candidate.entity.path, passage.source_hash)
                if prior_hash != passage.source_hash:
                    raise ValueError('mixed source generations in file proposals')
            combined = merged.setdefault(candidate.entity, Candidate(candidate.entity, [], {'rrf': 0.}))
            _max_signals(combined.signals, {k: v for k, v in candidate.signals.items() if k != 'rrf'})
            if candidate.entity not in seen:
                seen.add(candidate.entity)
                combined.signals['proposal_'+channel] = 1 / len(seen)
                combined.signals['rrf'] += 1 / (rrf_k + len(seen))
            positions = {p.span: i for i, p in enumerate(combined.passages)}
            for passage in candidate.passages:
                if passage.entity != candidate.entity:
                    raise ValueError('proposal contains another source owner')
                if passage.span in positions:
                    index = positions[passage.span]
                    prior = combined.passages[index]
                    signals = dict(prior.signals)
                    _max_signals(signals, passage.signals)
                    combined.passages[index] = replace(prior, signals=signals)
                else:
                    positions[passage.span] = len(combined.passages)
                    combined.passages.append(passage)
            combined.owned_regions = merge_spans((*combined.owned_regions, *candidate.owned_regions))
    return sorted(merged.values(), key=lambda c: (
        -c.signals.get('exact', 0), -c.signals['rrf'], c.entity.path,
        min(p.span.start_line for p in c.passages)))[:limit]
