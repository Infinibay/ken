"""Personalized PageRank over a unified file graph (Phase 4).

Import-affinity, test-affinity, and the propagation half of the
co-occurrence boost are three hand-built 1-hop propagations with ~15
constants between them. They are the first-order term of the same idea:
walk out from the files we already trust and lift their neighbours.

This module computes that directly — a random walk with restart (RWR /
personalized PageRank) over one weighted graph with typed edges:

  * **imports** — ``ci_imports`` (resolved file→file)
  * **test↔source** — filename-heuristic counterparts
  * **session co-occurrence** — files scored together in ``cr_session_scores``
  * **git co-change** — files changed in the same commit
    (``cr_commit_files``; optional — older DBs lack the table)

Degree normalisation inside the transition matrix subsumes the import
hub-damping hack; the restart probability α subsumes the per-boost
propagation/cap constants. Gated behind ``KEN_RANKER_PPR=1``; when on it
replaces ``apply_import_affinity`` / ``apply_test_affinity`` / the
co-occurrence propagation.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ken.ranker import RankedItem
from ken.ranker.boosts import (
    _PathIndex, _append_reason, _related_source_files, _related_tests, _is_test_path,
)

def _envf(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


# Defaults are deliberately conservative: PPR is validated as an *additive*
# channel (KEN_RANKER_PPR=add) that surfaces multi-hop + git-co-change
# neighbours the precise name/edge-exact boosts miss. Aggressive settings
# displace good hits on a sparse graph (measured); gentle settings are a
# clean Pareto win once co-change is ingested.
ALPHA = _envf("KEN_PPR_ALPHA", 0.8)          # restart prob (higher → nearer anchors)
ITERS = 3               # bounded propagation depth
PPR_MAX = _envf("KEN_PPR_MAX", 0.6)          # max contribution to a surfaced neighbour
PPR_MIN_FRAC = _envf("KEN_PPR_MINFRAC", 0.4)   # keep neighbours with p ≥ frac·max
PPR_MAX_NEIGHBORS = int(_envf("KEN_PPR_MAXN", 3))

W_IMPORT = 1.0
W_TEST = 1.0
W_COOC = 0.7
W_COCHANGE = 1.2

_COOC_MAX_SESSION = 25   # ignore mega-sessions/commits as fully-connected noise
_COCHANGE_MAX_COMMIT = 25


def ppr_mode() -> str:
    """'off' | 'add' (keep precise boosts, add PPR) | 'replace' (subsume them)."""
    raw = os.environ.get("KEN_RANKER_PPR", "").strip().lower()
    if raw in {"add", "additive"}:
        return "add"
    if raw in {"1", "true", "on", "yes", "replace"}:
        return "replace"
    return "off"


def ppr_enabled() -> bool:
    return ppr_mode() != "off"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


@dataclass
class _SparseGraph:
    """Directed edge arrays; storage and each walk cost O(files + edges)."""

    source: np.ndarray
    target: np.ndarray
    weight: np.ndarray
    degree: np.ndarray

    def walk(self, mass: np.ndarray) -> np.ndarray:
        # Only edge sources are indexed, so dangling nodes never divide by zero.
        return np.bincount(
            self.target,
            weights=self.weight * mass[self.source] / self.degree[self.source],
            minlength=len(self.degree),
        )


def _build_adjacency(
    conn: sqlite3.Connection, paths: list[str], idx: dict[str, int]
) -> _SparseGraph:
    n = len(paths)
    edges: dict[tuple[int, int], float] = defaultdict(float)

    def link(u: str, v: str, w: float) -> None:
        i, j = idx.get(u), idx.get(v)
        if i is None or j is None or i == j:
            return
        edges[i, j] += w
        edges[j, i] += w

    # imports
    for r in conn.execute(
        """
        SELECT src.path AS s, dst.path AS d
        FROM ci_imports i
        JOIN ci_files src ON src.id = i.from_file_id
        JOIN ci_files dst ON dst.id = i.to_file_id
        """
    ):
        link(str(r["s"]), str(r["d"]), W_IMPORT)

    # test ↔ source (filename heuristic)
    path_index = _PathIndex(paths)
    for path in paths:
        related = (
            _related_source_files(path, path_index)
            if _is_test_path(path)
            else _related_tests(path, path_index)
        )
        for other in related:
            link(path, other, W_TEST)

    # session co-occurrence
    _basket_edges(
        conn,
        "SELECT session_id AS grp, target_path AS path FROM cr_session_scores "
        "WHERE target_path IS NOT NULL AND score > 0",
        link,
        W_COOC,
        _COOC_MAX_SESSION,
    )

    # git co-change (optional)
    if _table_exists(conn, "cr_commit_files"):
        _basket_edges(
            conn,
            "SELECT commit_id AS grp, path FROM cr_commit_files WHERE path IS NOT NULL",
            link,
            W_COCHANGE,
            _COCHANGE_MAX_COMMIT,
        )
    source = np.fromiter((u for u, _ in edges), dtype=np.intp, count=len(edges))
    target = np.fromiter((v for _, v in edges), dtype=np.intp, count=len(edges))
    weight = np.fromiter(edges.values(), dtype=np.float64, count=len(edges))
    degree = np.bincount(source, weights=weight, minlength=n)
    return _SparseGraph(source, target, weight, degree)


def _basket_edges(
    conn: sqlite3.Connection, query: str, link: Callable[[str, str, float], None],
    weight: float, max_size: int,
) -> None:
    """Add clique edges among items sharing a group (session/commit)."""
    baskets: dict[int, list[str]] = defaultdict(list)
    for r in conn.execute(query):
        baskets[int(r["grp"])].append(str(r["path"]))
    for members in baskets.values():
        members = list(dict.fromkeys(members))
        if not (2 <= len(members) <= max_size):
            continue
        # Down-weight larger baskets so a big session/commit doesn't blast
        # a dense clique (market-basket support normalisation).
        w = weight / (len(members) - 1)
        for a_i in range(len(members)):
            for b_i in range(a_i + 1, len(members)):
                link(members[a_i], members[b_i], w)


def apply_ppr(conn: sqlite3.Connection, files: list[RankedItem]) -> None:
    """Surface structural neighbours of the current anchors via RWR."""
    if not files:
        return
    alpha = _envf("KEN_PPR_ALPHA", ALPHA)
    ppr_max = _envf("KEN_PPR_MAX", PPR_MAX)
    ppr_min_frac = _envf("KEN_PPR_MINFRAC", PPR_MIN_FRAC)
    max_neighbors = int(_envf("KEN_PPR_MAXN", PPR_MAX_NEIGHBORS))
    rows = conn.execute("SELECT path FROM ci_files ORDER BY path").fetchall()
    paths = [str(r["path"]) for r in rows]
    if len(paths) < 2:
        return
    idx = {p: i for i, p in enumerate(paths)}
    graph = _build_adjacency(conn, paths, idx)
    if not graph.weight.size:
        return

    n = len(paths)
    seed = np.zeros(n, dtype=np.float64)
    by_path = {it.target: it for it in files}
    for it in files:
        i = idx.get(it.target)
        if i is not None and it.score > 0:
            seed[i] += it.score
    total = seed.sum()
    if total <= 0:
        return
    seed /= total

    p = seed.copy()
    for _ in range(ITERS):
        p = alpha * seed + (1.0 - alpha) * graph.walk(p)

    # Contributions to NON-anchor files only (anchors already ranked).
    anchor_idx = {i for i, s in enumerate(seed) if s > 0}
    neighbours = [
        (i, p[i]) for i in range(n) if i not in anchor_idx and p[i] > 0
    ]
    if not neighbours:
        return
    p_max = max(val for _, val in neighbours)
    if p_max <= 0:
        return
    neighbours.sort(key=lambda t: t[1], reverse=True)
    for i, val in neighbours[:max_neighbors]:
        if val < ppr_min_frac * p_max:
            break
        contribution = ppr_max * (val / p_max)
        path = paths[i]
        if path in by_path:
            by_path[path].score += contribution
            by_path[path].reason = _append_reason(
                by_path[path].reason, f"ppr+{contribution:.1f}"
            )
        else:
            item = RankedItem(
                target=path,
                target_type="file",
                score=contribution,
                reason=f"ppr({contribution:.1f})",
            )
            files.append(item)
            by_path[path] = item
