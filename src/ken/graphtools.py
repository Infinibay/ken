"""Graph algorithms over ken's resolved import graph.

Pure-Python, dependency-free implementations of the classic structure
queries an agent needs but that no single embedding or grep can answer:

* ``architecture`` — Tarjan SCC (import cycles), topological layering,
  label-propagation communities, and PageRank hubs / sinks. Every result
  carries an **edge-coverage header** so the agent calibrates trust: a
  reported cycle is exact (uses only real edges), layers/communities are
  approximate when many imports are unresolved.
* ``blast_radius`` — multi-source reverse reachability over imports, unioned
  with test heuristics and (optionally) git co-change, with **per-channel
  evidence** rather than a fused black-box score. Honest about being a lower
  bound when imports are unresolved.

Neither tool invents a probability; they report exact graph facts plus how
much of the graph they could see.
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path


def _import_graph(conn) -> tuple[dict[int, str], dict[int, set[int]], int, int]:
    """Build the resolved import digraph.

    Returns ``(id->path, adjacency from->{to}, resolved_edges, total_edges)``.
    """
    paths = {int(r["id"]): r["path"] for r in conn.execute("SELECT id, path FROM ci_files")}
    adj: dict[int, set[int]] = defaultdict(set)
    resolved = 0
    for r in conn.execute(
        "SELECT from_file_id, to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL"
    ):
        a, b = int(r["from_file_id"]), int(r["to_file_id"])
        if a == b or a not in paths or b not in paths:
            continue
        adj[a].add(b)
        resolved += 1
    total = conn.execute("SELECT COUNT(*) AS n FROM ci_imports").fetchone()["n"]
    return paths, adj, resolved, int(total)


def _coverage(conn) -> dict:
    """Honest import-resolution breakdown: internal coverage excludes external deps."""
    row = conn.execute(
        """
        SELECT
          SUM(to_file_id IS NOT NULL)                         AS internal_resolved,
          SUM(resolution = 'unresolved')                      AS internal_gap,
          SUM(resolution = 'external')                        AS external,
          COUNT(*)                                            AS total
        FROM ci_imports
        """
    ).fetchone()
    internal_resolved = int(row["internal_resolved"] or 0)
    internal_gap = int(row["internal_gap"] or 0)
    external = int(row["external"] or 0)
    internal_total = internal_resolved + internal_gap
    pct = round(100.0 * internal_resolved / internal_total, 1) if internal_total else None
    return {
        "resolved": internal_resolved,
        "total": int(row["total"] or 0),
        "internal_resolved": internal_resolved,
        "internal_unresolved": internal_gap,
        "internal_total": internal_total,
        "external": external,
        "internal_coverage_pct": pct,
    }


def _tarjan_scc(nodes: list[int], adj: dict[int, set[int]]) -> list[list[int]]:
    """Iterative Tarjan strongly-connected-components (avoids recursion limit)."""
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    sccs: list[list[int]] = []
    counter = 0

    for start in nodes:
        if start in index:
            continue
        work = [(start, iter(sorted(adj.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp: list[int] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)
    return sccs


def _pagerank(nodes: list[int], adj: dict[int, set[int]], *, damping: float = 0.85,
              iters: int = 40) -> dict[int, float]:
    n = len(nodes)
    if n == 0:
        return {}
    rank = {v: 1.0 / n for v in nodes}
    out_deg = {v: len(adj.get(v, ())) for v in nodes}
    nodeset = set(nodes)
    for _ in range(iters):
        dangling = sum(rank[v] for v in nodes if out_deg[v] == 0)
        nxt = {v: (1.0 - damping) / n + damping * dangling / n for v in nodes}
        for v in nodes:
            if out_deg[v] == 0:
                continue
            share = damping * rank[v] / out_deg[v]
            for w in adj[v]:
                if w in nodeset:
                    nxt[w] += share
        rank = nxt
    return rank


def _communities(nodes: list[int], adj: dict[int, set[int]], *, iters: int = 20) -> dict[int, int]:
    """Synchronous-ish label propagation on the undirected projection."""
    undirected: dict[int, set[int]] = defaultdict(set)
    for a, tos in adj.items():
        for b in tos:
            undirected[a].add(b)
            undirected[b].add(a)
    label = {v: v for v in nodes}
    for _ in range(iters):
        changed = False
        for v in sorted(nodes):
            neigh = undirected.get(v)
            if not neigh:
                continue
            counts: dict[int, int] = defaultdict(int)
            for w in neigh:
                counts[label[w]] += 1
            # Most frequent neighbour label; ties broken by smallest label id
            # for determinism.
            best = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
            if label[v] != best:
                label[v] = best
                changed = True
        if not changed:
            break
    return label


def architecture(conn, *, depth: int = 2, limit: int = 20) -> dict:
    """Subsystems, layers, cycles, and hubs of the import graph (coverage-honest)."""
    paths, adj, resolved, total = _import_graph(conn)
    coverage = _coverage(conn)
    nodes = [n for n in paths if adj.get(n) or any(n in tos for tos in adj.values())]
    nodes = sorted(set(nodes))
    if not nodes:
        return {
            "ok": True,
            "edge_coverage": coverage,
            "cycles": [], "layers": [], "clusters": [], "hubs": [], "sinks": [],
            "note": "no resolved import edges — graph queries unavailable",
        }

    # --- cycles (high trust: only real edges) ---
    sccs = _tarjan_scc(nodes, adj)
    comp_of = {v: i for i, comp in enumerate(sccs) for v in comp}
    cycles = [sorted(paths[v] for v in comp) for comp in sccs if len(comp) > 1]
    cycles.sort(key=lambda c: (-len(c), c[0]))

    # --- topological layers over the SCC condensation (approximate) ---
    cond_adj: dict[int, set[int]] = defaultdict(set)
    for a, tos in adj.items():
        for b in tos:
            if comp_of[a] != comp_of[b]:
                cond_adj[comp_of[a]].add(comp_of[b])
    layer = _longest_path_layers(list(range(len(sccs))), cond_adj)
    layers_by_idx: dict[int, list[str]] = defaultdict(list)
    for comp_idx, comp in enumerate(sccs):
        for v in comp:
            layers_by_idx[layer[comp_idx]].append(paths[v])
    layers = [sorted(layers_by_idx[i]) for i in sorted(layers_by_idx)]

    # --- communities + hubs ---
    label = _communities(nodes, adj)
    clusters_raw: dict[int, list[int]] = defaultdict(list)
    for v in nodes:
        clusters_raw[label[v]].append(v)
    pr = _pagerank(nodes, adj)
    rev_adj: dict[int, set[int]] = defaultdict(set)
    for a, tos in adj.items():
        for b in tos:
            rev_adj[b].add(a)
    rpr = _pagerank(nodes, rev_adj)

    clusters = []
    for members in sorted(clusters_raw.values(), key=lambda m: (-len(m), paths[min(m)])):
        if len(members) < 2:
            continue
        member_paths = sorted(paths[v] for v in members)
        central = max(members, key=lambda v: pr.get(v, 0.0))
        clusters.append({
            "label": _common_dir(member_paths),
            "size": len(members),
            "central_file": paths[central],
            "members": member_paths[: max(1, int(limit))],
        })
    clusters = clusters[: max(1, int(limit))]

    hubs = sorted(nodes, key=lambda v: pr.get(v, 0.0), reverse=True)[: max(1, int(limit))]
    sinks = sorted(nodes, key=lambda v: rpr.get(v, 0.0), reverse=True)[: max(1, int(limit))]
    return {
        "ok": True,
        "edge_coverage": coverage,
        "trust": (
            "cycles are exact; layers/communities are approximate and degrade "
            "as unresolved imports rise"
        ),
        "cycles": cycles[: max(1, int(limit))],
        "layers": layers,
        "clusters": clusters,
        "hubs": [{"path": paths[v], "pagerank": round(pr[v], 5)} for v in hubs],
        "sinks": [{"path": paths[v], "reverse_pagerank": round(rpr[v], 5)} for v in sinks],
    }


def _longest_path_layers(nodes: list[int], adj: dict[int, set[int]]) -> dict[int, int]:
    """Assign each DAG node a layer = longest path from any source to it."""
    indeg = {v: 0 for v in nodes}
    for a in nodes:
        for b in adj.get(a, ()):
            indeg[b] = indeg.get(b, 0) + 1
    q = deque(sorted(v for v in nodes if indeg[v] == 0))
    layer = {v: 0 for v in nodes}
    while q:
        v = q.popleft()
        for b in sorted(adj.get(v, ())):
            layer[b] = max(layer[b], layer[v] + 1)
            indeg[b] -= 1
            if indeg[b] == 0:
                q.append(b)
    return layer


def _common_dir(paths: list[str]) -> str:
    if not paths:
        return ""
    parts = [Path(p).parent.as_posix() for p in paths]
    common = parts[0]
    for p in parts[1:]:
        while common and not (p == common or p.startswith(common + "/")):
            common = "/".join(common.split("/")[:-1])
    return common or "(root)"


def blast_radius(conn, path: str, *, max_hops: int = 4, project_root: Path | None = None) -> dict:
    """Files likely affected by editing *path*, with per-channel evidence."""
    target = Path(path).as_posix()
    if target.startswith("./"):
        target = target[2:]
    row = conn.execute("SELECT id, path FROM ci_files WHERE path = ?", (target,)).fetchone()
    if row is None:
        return {"ok": False, "error": "file not indexed", "path": target}
    target_id = int(row["id"])

    # Reverse import reachability: who (transitively) imports target.
    rev: dict[int, set[int]] = defaultdict(set)
    paths = {int(r["id"]): r["path"] for r in conn.execute("SELECT id, path FROM ci_files")}
    for r in conn.execute(
        "SELECT from_file_id, to_file_id FROM ci_imports WHERE to_file_id IS NOT NULL"
    ):
        rev[int(r["to_file_id"])].add(int(r["from_file_id"]))
    # Count only *internal* resolution gaps — external deps would never be a
    # traceable edge, so including them would overstate the blind spot.
    unresolved = conn.execute(
        "SELECT COUNT(*) AS n FROM ci_imports WHERE resolution = 'unresolved'"
    ).fetchone()["n"]
    internal_total = conn.execute(
        "SELECT COUNT(*) AS n FROM ci_imports WHERE to_file_id IS NOT NULL OR resolution = 'unresolved'"
    ).fetchone()["n"]

    hops: dict[int, int] = {target_id: 0}
    q: deque[int] = deque([target_id])
    while q:
        v = q.popleft()
        if hops[v] >= max(1, int(max_hops)):
            continue
        for importer in sorted(rev.get(v, ())):
            if importer not in hops:
                hops[importer] = hops[v] + 1
                q.append(importer)

    evidence: dict[str, dict] = {}
    for fid, h in hops.items():
        if fid == target_id:
            continue
        p = paths.get(fid)
        if p:
            evidence[p] = {"path": p, "hops": h, "evidence": [f"imports(hop {h})"]}

    # Test heuristics.
    from ken.search import _find_tests_for_row

    for t in _find_tests_for_row(conn, row, limit=50):
        e = evidence.setdefault(t["path"], {"path": t["path"], "hops": 1, "evidence": []})
        e["evidence"].append(f"test-of ({t['reason']})")

    # Git co-change (best-effort; only if history is present).
    try:
        from ken.cochange import cochange as _cochange

        co = _cochange(conn, target, project_root=project_root,
                       auto_ingest=project_root is not None, limit=30)
        for partner in co.get("partners", []):
            e = evidence.setdefault(
                partner["path"], {"path": partner["path"], "hops": 1, "evidence": []}
            )
            e["evidence"].append(f"co-changed {partner['support']}x")
    except Exception:  # pragma: no cover - co-change is optional
        pass

    out = sorted(evidence.values(), key=lambda e: (e["hops"], -len(e["evidence"]), e["path"]))
    return {
        "ok": True,
        "path": target,
        "direct_importers": [e["path"] for e in out if e["hops"] == 1
                             and any(x.startswith("imports") for x in e["evidence"])],
        "impacted": out,
        "coverage_note": (
            f"{unresolved}/{internal_total} internal imports are unresolved and not "
            "traced (external deps excluded) — this is a LOWER bound; verify before "
            "assuming safety"
        ),
    }
