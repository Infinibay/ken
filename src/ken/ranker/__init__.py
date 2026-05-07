"""Multi-channel context ranker.

Public surface:

    rank(conn, agent_id, current_iteration, prompt, prompt_embedding) -> RankResult
    render_block(result) -> str

The ranker is **synchronous and quick** by design — the daemon calls
it inline on a UserPromptSubmit. Cosine sweeps are vectorised numpy
on the symbol/file embeddings (~10K rows is nothing); SQL queries are
narrow.

Channels (each independently scores rows from scratch):

  1. **Reactive** — what the current session is touching, weighted by
     productivity pattern (`ranker.channels.reactive`).
  2. **Predictive** — what past sessions with semantically similar
     prompts ended up using (`ranker.channels.predictive`).
  3. **Fuzzy** — cosine sim of the prompt against indexed symbol /
     file embeddings (`ranker.channels.fuzzy`).
  4. *(skipped)* — Findings; no `findings` table yet. Hook back in
     later if we add a "scratch notes" surface.

Post-processing boosts (modify scored items, never create new ones):

  5. **Co-occurrence** — files frequently accessed alongside the
     current top-ranked files in past sessions (`ranker.boosts.cooc`).
  6. *(skipped)* — Import graph; needs an import resolver to map
     "from auth import login" → src/auth.py before the join is useful.
  7. **Freshness** — multiplicative bump for files modified recently
     on disk (`ranker.boosts.freshness`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Top-level confidence gate: if every channel produces nothing scoring
# above this, we suppress the entire <context-rank> block. Empty-but-
# correct beats "here's noise the model now has to filter out".
MIN_CONFIDENCE = 1.5


@dataclass
class RankedItem:
    target: str            # path (file) or qualname (symbol)
    target_type: str       # 'file' | 'symbol'
    score: float
    reason: str = ""

    def __lt__(self, other: "RankedItem") -> bool:
        return self.score < other.score


@dataclass
class RankResult:
    files: list[RankedItem] = field(default_factory=list)
    symbols: list[RankedItem] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.files and not self.symbols

    @property
    def top_score(self) -> float:
        best = 0.0
        for item in (*self.files, *self.symbols):
            best = max(best, item.score)
        return best


def rank(
    conn,
    *,
    agent_id: str,
    current_iteration: int,
    prompt: str,
    prompt_embedding: np.ndarray,
    top_files: int = 8,
    top_symbols: int = 5,
) -> RankResult:
    """Run all channels + boosts and return a confidence-gated result."""
    from ken.ranker import boosts, channels, merge

    explicit_files, explicit_symbols = channels.explicit_mentions(conn, prompt)
    reactive = channels.reactive_scores(conn, agent_id, current_iteration)
    predictive = channels.predictive_scores(conn, prompt_embedding)
    fuzzy_files, fuzzy_symbols = channels.fuzzy_scores(conn, prompt_embedding)

    files = merge.merge_files(explicit_files, reactive, predictive, fuzzy_files)
    symbols = merge.merge_symbols([*explicit_symbols, *fuzzy_symbols])

    boosts.apply_freshness(conn, files)
    boosts.apply_cooc(conn, files)
    boosts.apply_dismissal_penalty(conn, prompt_embedding, files)

    files.sort(reverse=True)
    symbols.sort(reverse=True)

    result = RankResult(files=files[:top_files], symbols=symbols[:top_symbols])
    if result.top_score < MIN_CONFIDENCE:
        return RankResult()  # confidence gate
    return result


__all__ = [
    "MIN_CONFIDENCE",
    "RankedItem",
    "RankResult",
    "rank",
]
