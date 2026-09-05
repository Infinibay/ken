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
  4. **Findings** — durable notes saved by `ken_remember` / `ken remember`.

Post-processing boosts:

  5. **Symbol-file affinity** — high-confidence symbol hits surface
     their containing file (`ranker.boosts.symbol_file_affinity`).
  6. **Co-occurrence** — files frequently accessed alongside the
     current top-ranked files in past sessions (`ranker.boosts.cooc`).
  7. **Import/test affinity** — direct import neighbours and likely
     tests for current anchors (`ranker.boosts`).
  8. **Freshness** — multiplicative bump for files modified recently
     on disk (`ranker.boosts.freshness`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import sqlite3

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
        if self.score != other.score:
            return self.score < other.score
        # Stable tiebreak by target. We invert the comparison so that
        # post-`reverse=True` sort gives ascending alphabetical order
        # for ties — predictable across runs and platforms.
        return self.target > other.target


@dataclass
class FindingItem:
    topic: str
    content: str
    tags: list[str] = field(default_factory=list)
    score: float = 0.0
    reason: str = "finding"

    def __lt__(self, other: "FindingItem") -> bool:
        if self.score != other.score:
            return self.score < other.score
        return self.topic > other.topic


@dataclass
class RankResult:
    files: list[RankedItem] = field(default_factory=list)
    symbols: list[RankedItem] = field(default_factory=list)
    findings: list[FindingItem] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.files and not self.symbols and not self.findings

    @property
    def top_score(self) -> float:
        best = 0.0
        for item in (*self.files, *self.symbols):
            best = max(best, item.score)
        for finding in self.findings:
            best = max(best, finding.score)
        return best


@dataclass
class _RankTrace:
    """Optional snapshots from the production pipeline, used by explain()."""

    channels: dict[str, list[RankedItem]] = field(default_factory=dict)
    findings: list[FindingItem] = field(default_factory=list)
    stages: dict[str, RankResult] = field(default_factory=dict)
    gate: float = MIN_CONFIDENCE
    suppressed: bool = False

    def capture(self, name: str, files: list[RankedItem], symbols: list[RankedItem]) -> None:
        self.stages[name] = RankResult(
            files=[replace(it) for it in files],
            symbols=[replace(it) for it in symbols],
        )


def rank(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    current_iteration: int,
    prompt: str,
    prompt_embedding: np.ndarray,
    top_files: int = 8,
    top_symbols: int = 5,
    top_findings: int = 3,
    project_root: Path | None = None,
    include_reactive: bool = True,
    _trace: _RankTrace | None = None,
) -> RankResult:
    """Run all channels + boosts and return a confidence-gated result."""
    from ken.ranker import boosts, channels, fusion, merge

    mode = fusion.fusion_mode()

    # One cosine sweep over recent prompts, shared between predictive
    # (positive evidence) and the dismissal penalty (negative).
    similar = channels.similar_past_sessions(
        conn, prompt_embedding, exclude_agent_id=agent_id
    )

    explicit_files, explicit_symbols = channels.explicit_mentions(conn, prompt)
    reactive = (
        channels.reactive_scores(conn, agent_id, current_iteration)
        if include_reactive
        else []
    )
    predictive = channels.predictive_scores(conn, similar)
    fuzzy_files, fuzzy_symbols = channels.fuzzy_scores(conn, prompt_embedding)
    doc_files, doc_symbols = channels.doc_intent_scores(conn, prompt_embedding)
    literal_files = channels.literal_content_scores(
        conn, prompt, project_root=project_root
    )
    lexical_files, lexical_symbols = channels.lexical_scores(
        conn, prompt, agent_id=agent_id, project_root=project_root
    )
    findings = channels.finding_scores(conn, prompt_embedding)

    if _trace is not None:
        _trace.channels = {
            name: [replace(it) for it in items]
            for name, items in {
                "explicit_files": explicit_files, "explicit_symbols": explicit_symbols,
                "reactive": reactive, "predictive": predictive,
                "fuzzy_files": fuzzy_files, "fuzzy_symbols": fuzzy_symbols,
                "doc_intent_files": doc_files, "doc_intent_symbols": doc_symbols,
                "literal_files": literal_files, "lexical_files": lexical_files,
                "lexical_symbols": lexical_symbols,
            }.items()
        }
        _trace.findings = [replace(it) for it in findings]

    def capture(name: str) -> None:
        if _trace is not None:
            _trace.capture(name, files, symbols)

    symbols = merge.merge_symbols(
        [*explicit_symbols, *fuzzy_symbols, *doc_symbols, *lexical_symbols]
    )
    channel_file_lists = [
        explicit_files,
        reactive,
        predictive,
        fuzzy_files,
        doc_files,
        literal_files,
        lexical_files,
    ]
    if mode == "logodds":
        files = fusion.fuse_files(channel_file_lists)
    else:
        files = merge.merge_files(*channel_file_lists)
    capture("merge")

    boosts.apply_symbol_file_affinity(conn, files, symbols)
    capture("symbol_file_affinity")
    boosts.apply_freshness(conn, files)
    capture("freshness")
    from ken.ranker import ppr as ppr_mod

    ppr_mode = ppr_mod.ppr_mode()
    if ppr_mode != "replace":
        boosts.apply_cooc(conn, files)
    capture("cooc")
    if ppr_mode != "replace":
        boosts.apply_test_affinity(conn, files)
    capture("test_affinity")
    if ppr_mode != "replace":
        boosts.apply_import_affinity(conn, files)
    capture("import_affinity")
    if ppr_mode in {"add", "replace"}:
        ppr_mod.apply_ppr(conn, files)
    capture("ppr")
    boosts.apply_dismissal_penalty(conn, files, similar)
    capture("dismissal")
    boosts.apply_implementation_intent(files, prompt)
    capture("implementation_intent")
    boosts.apply_documentation_intent(files, prompt)
    capture("documentation_intent")
    boosts.apply_language_intent(files, symbols, prompt)
    capture("language_intent")
    if project_root is not None:
        files, symbols = _drop_missing_paths(project_root, files, symbols)

    files.sort(reverse=True)
    symbols.sort(reverse=True)
    findings.sort(reverse=True)

    result = RankResult(
        files=files[:top_files],
        symbols=symbols[:top_symbols],
        findings=findings[:top_findings],
    )
    gate = fusion.LOGODDS_GATE if mode == "logodds" else MIN_CONFIDENCE
    if _trace is not None:
        _trace.gate = gate
        _trace.suppressed = result.top_score < gate
        capture("before_gate")
    if result.top_score < gate:
        return RankResult()  # confidence gate
    return result


def _drop_missing_paths(
    project_root: Path,
    files: list[RankedItem],
    symbols: list[RankedItem],
) -> tuple[list[RankedItem], list[RankedItem]]:
    """Remove ranked files/symbols whose indexed path no longer exists."""
    root = project_root.resolve()
    live_files = [it for it in files if _path_exists(root, it.target)]
    live_symbols = [
        it for it in symbols
        if (path := _symbol_target_path(it.target)) is not None
        and _path_exists(root, path)
    ]
    return live_files, live_symbols


def _path_exists(root: Path, rel: str) -> bool:
    try:
        return (root / rel).exists()
    except OSError:
        return False


def _symbol_target_path(target: str) -> str | None:
    try:
        _qualname, location = target.rsplit(" (", 1)
        path, line = location.rsplit(":", 1)
    except ValueError:
        return None
    if not line.endswith(")"):
        return None
    line_no = line[:-1]
    return path if line_no.isdigit() else None


__all__ = [
    "MIN_CONFIDENCE",
    "FindingItem",
    "RankedItem",
    "RankResult",
    "rank",
]
