"""Acquire only the local evidence demanded by a positive hazard query.

Hazard predicates stay in structural.effects. This profile only removes work
that cannot contribute to a HAS_HAZARD-only query; all other plans use the full
frontend and linker. Profile-specific unit keys prevent partial IR reuse there.
"""

from __future__ import annotations

import json

from ken.structural.model import IR, Fact, FactIndex


def supports(program) -> bool:
    if not program.graph:
        return False
    from .graph import relational_plan

    plan = relational_plan(program)
    return (
        bool(plan.nodes)
        and not plan.definitions
        and all(
            node.kind == "fact"
            and node.value.mode == "require"
            and node.value.relation == "HAS_HAZARD"
            for node in plan.nodes
        )
    )


def lower(source: bytes, language: str, path: str) -> IR:
    from ken.structural.effects import syntax_effects
    from ken.structural.frontend import Lowerer, lower_source

    if language == "python":
        frontend = Lowerer(source, language, path)
        frontend.declare(frontend.tree.root_node, frontend.module)
        syntax_effects(frontend)
        ir = frontend.ir
        if frontend.tree.root_node.has_error:
            ir.diagnostics.append("parse errors: semantic absence is unknown")
    else:
        # Other frontends' hazards may depend on binding semantics (e.g. NaN
        # shadowing). Keep their accredited lowering until equivalence is proved.
        ir = lower_source(source, language, path)
    facts = [fact for fact in ir.facts if fact.relation == "HAS_HAZARD"]
    subjects = {fact.subject for fact in facts}
    return IR(
        path,
        language,
        entities={
            key: entity for key, entity in ir.entities.items() if key in subjects
        },
        facts=facts,
        capabilities={"syntax_hazards"},
        diagnostics=ir.diagnostics,
        relations={"HAS_HAZARD"},
    )


def index(store, snapshot, check) -> FactIndex:
    """Read selected fact columns; never deserialize whole project units."""
    graph = IR(
        "<project>",
        "mixed",
        view="query",
        relations={"HAS_HAZARD"},
        capabilities={"syntax_hazards"},
    )
    for row in store.db.execute(
        "SELECT f.subject,f.object,f.context,f.evidence FROM k2_snapshot_units s "
        "JOIN k2_facts f ON f.unit_id=s.unit_id "
        "WHERE s.snapshot_id=? AND f.relation='HAS_HAZARD' ORDER BY s.path,f.ordinal",
        (snapshot,),
    ):
        check()
        subject, obj, context, evidence = row
        graph.facts.append(
            Fact(subject, "HAS_HAZARD", obj, json.loads(context), json.loads(evidence))
        )
    return FactIndex(graph)
