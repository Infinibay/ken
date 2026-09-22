"""Snapshot graph execution, with a disposable normalized graph disk artifact."""

from __future__ import annotations

import time
from hashlib import sha256

from ken.structural.model import FactIndex
from ken.structural.query import QueryBudget, _Exhausted
from ken.structural.query_view import normalize_query_graph
from ken.structural.relational import Executor
from ken.structural.semantic import link_project
from ken.structural_store import Store
from ken.structural_store.graph_index import GraphIndex
from ken.structural_store.graph_projection import publish
from ken.structural_store.graph_revision import graph_revision
from ken.structural_store.leases import renew

from .graph import relational_plan
from .outcome import Outcome

CODEC = "kql2-relational-columns/2"


def graph_index(store: Store, snapshot: int, check) -> tuple[FactIndex, bool]:
    from .request import phase

    phase("graph", execution_phase="graph")
    row = store.db.execute(
        "SELECT manifest,profile FROM k2_snapshots WHERE snapshot_id=?", (snapshot,)
    ).fetchone()
    if row is None:
        raise ValueError("snapshot does not exist")
    key = sha256(repr((CODEC, row, graph_revision())).encode()).hexdigest()
    check()
    found = store.db.execute('SELECT graph_id FROM k2_graphs JOIN k2_graph_publications USING(graph_id) WHERE fingerprint=? AND ready=1', (key,)).fetchone()
    if found is not None:
        return GraphIndex(store, found[0]), True
    units = []
    for (unit,) in store.db.execute(
        "SELECT unit_id FROM k2_snapshot_units WHERE snapshot_id=? ORDER BY path",
        (snapshot,),
    ):
        check()
        units.append(store.load_unit(unit))
    phase("link", execution_phase="link")
    graph = normalize_query_graph(link_project(units))
    del units
    check()
    try:
        phase("graph_persist", execution_phase="graph_persist")
        graph_id = publish(store, snapshot, key, graph, check=check)
        return GraphIndex(store, graph_id), False
    except MemoryError:
        # Retention limits do not force graph matching into project-sized RAM.
        # A private temporary SQLite index is still queried through columns.
        temporary = Store(cache_mb=0)
        try:
            temporary_snapshot = temporary.publish([], expected_parent=None, profile=key)
            graph_id = publish(temporary, temporary_snapshot, key, graph, check=check)
            return GraphIndex(temporary, graph_id, owns_store=True), False
        except BaseException:
            temporary.close()
            raise



def execute_graph(
    program,
    store,
    snapshot,
    *,
    reference,
    timeout_ms,
    max_states,
    max_rows,
    cancelled,
    profile=False,
):
    started = time.monotonic()

    def check():
        if cancelled and cancelled():
            raise _Exhausted("cancelled")
        if timeout_ms is not None and (time.monotonic() - started) * 1000 >= timeout_ms:
            raise _Exhausted("timeout_ms")
        renew(store)

    index = engine = None
    try:
        from . import local_hazards

        local = local_hazards.supports(program) and not reference
        if local:
            index, hit = local_hazards.index(store, snapshot, check), False
        else:
            index, hit = graph_index(store, snapshot, check)
        from .request import phase
        phase("query", execution_phase="query")
        plan = relational_plan(program)
        check()
        budget = QueryBudget(
            max_states=max_states,
            max_rows=max_rows,
            max_matches=max_rows,
            timeout_ms=None,
        )
        engine = Executor(index, {}, budget, profile=profile)
        engine.check, engine.reference = check, reference
        result = engine.execute(plan)
    except _Exhausted as exc:
        return Outcome(
            complete=False,
            reason=str(exc),
            elapsed_ms=(time.monotonic() - started) * 1000,
        )
    finally:
        if engine is not None:
            engine.close()
        if isinstance(index, GraphIndex):
            index.close()

    def projected(value):
        usage = getattr(engine, "usage_metadata", {}).get(value)
        return {"id": value, **usage} if usage is not None else value

    rows = [
        tuple(projected(match["bindings"]["$" + name]) for name in plan.exports)
        for match in result["matches"]
    ]
    return Outcome(
        rows=rows,
        complete=result["complete"],
        unknown_candidates=len(
            [r for r in result["unknown"] if not r.startswith("budget:")]
        ),
        reason=next(iter(result["unknown"]), None),
        states=result["stats"]["states"],
        scanned_nodes=result["stats"]["rows_examined"],
        elapsed_ms=(time.monotonic() - started) * 1000,
        plan=[
            {
                "operator": "relational_graph",
                "acquisition": "local_hazards" if local else "linked_graph",
                "optimized": not reference,
                "graph_disk_hit": hit,
                "patterns": len(plan.definitions),
                "branches": "preserved",
            }
        ],
        optional_evidence=[
            {"row": i, "evidence": m["evidence"]}
            for i, m in enumerate(result["matches"])
        ],
        order_keys=[() for _ in rows],
        profile=engine.profile or [],
    )
