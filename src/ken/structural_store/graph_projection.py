"""Publish one immutable normalized graph transactionally into native columns."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from itertools import islice

from ken.structural.model import IR

from .graph_operation_attributes import OperationAttributes
from .graph_publication import Publication
from .graph_terms import Terms
from .graph_values import ValueWriter


def publish(
    store,
    snapshot: int,
    key: str,
    ir: IR,
    *,
    analysis=None,
    check: Callable[[], None] | None = None,
    progress=None,
    consume: bool = False,
    resume: bool = False,
) -> int:
    """Publish a complete graph, optionally taking ownership of its collections.

    ``consume=True`` is for private acquisition buffers: records are released as
    they reach disk, including on failure. Shared/reference IR stays unchanged
    by default. A failed publication never leaves a readable partial graph.
    ``resume=True`` is only safe for an identical ordered input snapshot; fresh
    normalization can assign different ordinals despite the same source revision.
    """
    if ir.view != "query":
        raise ValueError("expected normalized query graph")
    with Publication(
        store, snapshot, key, ir, check, progress, resume=resume
    ) as publication:
        if publication.existing:
            return publication.graph
        graph = publication.graph
        terms = Terms(store.db, graph)
        values = ValueWriter(store.db, graph, terms)
        offsets = {
            table: publication.position("k2_graph_" + table)
            for table in ("entities", "operations", "facts")
        }
        if any(offsets[name] > len(getattr(ir, name)) for name in offsets):
            raise ValueError("partial graph does not match input cardinality")
        with publication.transaction():
            store.db.execute(
                "DELETE FROM k2_graph_capabilities WHERE graph_id=?", (graph,)
            )
            store.db.execute(
                "DELETE FROM k2_graph_relations WHERE graph_id=?", (graph,)
            )
            metadata = values.put(
                {
                    "diagnostics": ir.diagnostics,
                    "relations": sorted(ir.relations),
                    "entities": len(ir.entities),
                    "operations": len(ir.operations),
                    "facts": len(ir.facts),
                    "analysis": analysis or {},
                }
            )
            store.db.execute(
                "UPDATE k2_graphs SET metadata=? WHERE graph_id=?", (metadata, graph)
            )

        insert = publication.insert

        def entities(skip):
            if consume:
                # Snapshot keys once: restarting dict iteration after each pop
                # would repeatedly traverse deleted slots and become quadratic.
                for i, entity_id in enumerate(tuple(ir.entities)):
                    entity = ir.entities.pop(entity_id)
                    if i >= skip:
                        yield entity
                ir.entities.clear()
            else:
                yield from islice(ir.entities.values(), skip, None)

        def records(items, skip):
            for i, item in enumerate(items):
                if i >= skip:
                    yield item
                if consume:
                    items[i] = None
            if consume:
                items.clear()

        insert(
            "k2_graph_capabilities", 2, ((graph, c) for c in sorted(ir.capabilities))
        )
        owners = {
            f.object: f.subject
            for f in ir.facts
            if f.relation in ("DECLARES", "HAS_PARAMETER", "HAS_FIELD", "HAS_METHOD")
        }
        owners.update(
            {f.subject: f.object for f in ir.facts if f.relation == "OWNED_BY"}
        )
        insert(
            "k2_graph_entities",
            13,
            (
                (
                    graph,
                    i,
                    terms.put(e.id),
                    terms.put(e.kind),
                    e.name,
                    terms.put(e.path),
                    e.line,
                    e.end_line,
                    values.put(e.attrs),
                    terms.put(e.attrs.get("owner")),
                    e.attrs.get("start_byte"),
                    e.attrs.get("end_byte"),
                    terms.put(owners.get(e.id, e.attrs.get("owner"))),
                )
                for i, e in enumerate(
                    entities(offsets["entities"]), start=offsets["entities"]
                )
            ),
        )
        del owners
        insert(
            "k2_graph_operations",
            12,
            (
                (
                    graph,
                    i,
                    terms.put(o.id),
                    terms.put(o.kind),
                    terms.put(o.native_kind),
                    terms.put(o.parent),
                    terms.put(o.role),
                    o.start,
                    o.end,
                    o.line,
                    terms.put(o.owner),
                    values.put(o.attrs),
                )
                for i, o in enumerate(
                    records(ir.operations, offsets["operations"]),
                    start=offsets["operations"],
                )
            ),
        )
        counts: Counter[int] = Counter()
        if offsets["facts"]:
            counts.update(
                dict(
                    store.db.execute(
                        "SELECT relation,count(*) FROM k2_graph_facts WHERE graph_id=? GROUP BY relation",
                        (graph,),
                    )
                )
            )

        def facts():
            for i, f in enumerate(
                records(ir.facts, offsets["facts"]), start=offsets["facts"]
            ):
                relation = terms.put(f.relation)
                counts[relation] += 1
                yield (
                    graph,
                    i,
                    terms.put(f.subject),
                    relation,
                    terms.put(f.object),
                    attributes.put(i, f),
                    values.put(f.evidence),
                )

        attributes = OperationAttributes(store.db, graph, values, terms)
        insert("k2_graph_facts", 7, facts())
        insert(
            "k2_graph_relations",
            3,
            ((graph, rel, count) for rel, count in counts.items()),
        )
        return graph
