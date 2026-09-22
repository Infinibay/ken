"""Relational join policy, with explicit binding and evidence barriers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import relational_operators
from .query import Clause, _bind, _resolve, _variable
from .relational_ir import Node
from .relational_terms import compare as _compare

if TYPE_CHECKING:
    from .relational import Executor


def clause_size(engine: Executor, clause: Clause, bindings: dict[str, str]) -> int:
    """How many rows this clause would yield for one representative row.

    ``len(index.rows(...))`` only counts the relation slice; it ignores a
    clause's kind literals and attribute filters. That rated a generator like
    ``call(name: /encode/)`` -- which matches 171 of ~30k calls -- as if it
    enumerated the whole relation, so the optimizer put it last and the join
    cross-producted millions of rows before the filter removed them.

    The memory reference counts matching rows; native storage estimates from
    indexed necessary predicates. Estimates are cached per endpoint shape and
    only decide join order, never which rows a query returns.
    """
    sres = _resolve(clause.subject, bindings)
    ores = _resolve(clause.object, bindings)
    key = (id(clause), sres, ores)
    cached = engine._sizes.get(key)
    if cached is not None:
        return cached
    native = getattr(engine.index, 'estimate_clause', None)
    if native is not None:
        size = native(clause, sres, ores)
        engine._sizes[key] = size
        return size
    facts = engine.index.rows(clause.relation, sres, ores)
    subject_filters = sres is not None or (
        not _variable(clause.subject) and clause.subject != "_"
    )
    object_filters = ores is not None or (
        not _variable(clause.object) and clause.object != "_"
    )
    if not clause.attrs and not subject_filters and not object_filters:
        size = len(facts)
    else:
        size = 0
        for fact in engine.candidates(clause, sres, ores):
            if sres is not None and fact.subject != sres:
                continue
            if ores is not None and fact.object != ores:
                continue
            probe: dict[str, str] = {}
            if (
                subject_filters
                and sres is None
                and not _bind(clause.subject, fact.subject, probe)
            ):
                continue
            if (
                object_filters
                and ores is None
                and not _bind(clause.object, fact.object, probe)
            ):
                continue
            if not all(
                _compare(fact.attrs.get(k), op, value) for k, op, value in clause.attrs
            ):
                continue
            size += 1
    engine._sizes[key] = size
    return size


def where_ready(node: Node, bound: set[str]) -> bool:
    first, _, second = node.value
    return all(
        not _variable(term) or term.split(".")[0] in bound for term in (first, second)
    )


def pool_boundary(engine: Executor, pending: list[Node], bound: set[str]) -> int:
    """End of the stretch of nodes whose order cannot change a result.

    A fact clause may be evaluated at any point in a conjunction: it only adds
    a binding and filters the rows it cannot satisfy. The exceptions are the
    barriers (negation, aggregates, named queries, path and unions own binding
    and scope semantics) and a ``where`` whose operands are not bound yet --
    crossing that one would let a later fact bind a role the ``where`` would
    otherwise have reported as ``attribute:missing``.

    ``different`` and ready ``where`` constraints are *not* boundaries: they
    are pure row filters, so they can be crossed and applied early. Keeping
    the whole stretch reorderable is what lets a cheap check run before an
    expensive fan-out instead of after it.
    """
    for index, node in enumerate(pending):
        if (
            node.kind not in relational_operators.OPERATORS
            or relational_operators.OPERATORS[node.kind].barrier
        ) or (node.kind == "where" and not engine.where_ready(node, bound)):
            return index
    return len(pending)


def ready_filter(engine: Executor, pending: list[Node], bound: set[str]) -> int | None:
    """Index of a constraint whose roles are already bound, if any.

    ``different`` and ``where`` remove exactly the rows they would remove at
    the end, so evaluating them as soon as their roles exist cannot change a
    result -- but it stops the join from multiplying rows that are about to
    be discarded. In the ``mediator`` catalogue rule the three ``different``
    clauses used to run after 1.8M rows had been built and then removed every
    one of them.
    """
    for index, node in enumerate(pending):
        if node.kind == "different":
            first, second = node.value
            if first in bound and second in bound:
                return index
        elif node.kind == "where" and engine.where_ready(node, bound):
            return index
    return None


def source_pruned_plan(
    engine: Executor, nodes: list[Node], initial: set[str]
) -> list[Node]:
    """Move pure restrictions before source matchers, preserving dependencies.

    BODY is expensive, but it is not a scope boundary for a conjunction over
    already selected declarations. New domain generators stay after BODY;
    its captured outputs are the actual
    dependency boundary. Never move a constraint that reads those outputs;
    never cross general unions, absence, aggregation, paths or named-query
    scopes. Single-fact alternatives with identical endpoints are positive
    scans; an independent domain can also follow a proven positive union.
    Source receiver/type operators are also pure, with explicit output roles.
    The remaining join planner can then choose selective subtype/override
    facts before enumerating method bodies, regardless of authoring order.
    """
    key = (id(nodes), frozenset(initial))
    cached = engine._source_plans.get(key)
    if cached is not None and cached[0] is nodes:
        return cached[1]
    plan = [_fact_union(node) for node in nodes]
    # A body-free positive dependency is a relation: seed its exported roles
    # from the caller's fact joins instead of materializing its Cartesian
    # product first. BODY, scope, aggregation and proof captures prevent this
    # transformation; prebinding their outputs can change their semantics.
    position = 0
    while position < len(plan):
        dependency = plan[position]
        if dependency.kind == "match" and not dependency.value[2]:
            name, bindings, _ = dependency.value
            child = engine.queries.get(name)
            if (child is not None and set(bindings) == set(child.exports)
                    and _positive_relation(child.nodes)):
                # Omitting an export introduces an existential projection.
                # Its alternative-proof group is a scope boundary: moving a
                # caller fact through it would place that fact inside the group.
                end = position + 1
                while end < len(plan) and plan[end].kind in {"fact", "fact_union"}:
                    end += 1
                following = plan[position + 1:end]
                produced = {
                    term for node in following
                    for clause in (node.value if node.kind == "fact_union" else (node.value,))
                    for term in (clause.subject, clause.object) if _variable(term)
                }
                if produced & set(bindings.values()):
                    plan[position:end] = following + [dependency]
                    position = end
                    continue
        position += 1
    # An independent domain before a positive union repeats every branch for
    # each domain member. Delay it until the union has produced its witnesses.
    # Only a single fact followed by a fully understood positive union is
    # eligible: scopes that embed incoming evidence (not/count/optional) remain
    # barriers, as do all operators whose dependencies we cannot prove here.
    if len(plan) >= 2 and plan[0].kind == "fact" and plan[1].kind == "any":
        fact = plan[0].value
        factor = {t for t in (fact.subject, fact.object) if _variable(t)}
        dependencies = _positive_union_roles(plan[1])
        if factor and dependencies is not None and not factor & (dependencies | initial):
            plan[0], plan[1] = plan[1], plan[0]

    def roles(node: Node) -> set[str]:
        if node.kind in {"fact", "fact_union"}:
            fact = node.value if node.kind == "fact" else node.value[0]
            terms = (fact.subject, fact.object)
        elif node.kind == "where":
            terms = (node.value[0], node.value[2])
        elif node.kind == "different":
            terms = node.value
        else:
            return set()
        return {term.split(".")[0] for term in terms if _variable(term)}

    def outputs(node: Node) -> set[str]:
        if node.kind == "source_body":
            # Source AST roles omit '$'; relational terms include it.
            return {"$" + role.lstrip("$") for role in node.value.outputs}
        if node.kind == "source_receiver":
            return {node.value[1]}
        if node.kind == "match":
            # A completed named query binds every exported argument. It is
            # still a motion barrier, but its outputs are available to
            # restrictions hoisted across a later source matcher.
            _, bindings, proof = node.value
            return set(bindings.values()) | ({proof} if proof else set())
        if node.kind in {"fact", "fact_union"}:
            return roles(node)
        return set()

    position = 0
    bound = set(initial)
    while position < len(plan):
        matcher = plan[position]
        if matcher.kind in {"source_body", "source_type", "source_receiver"}:
            # Only semijoin-like restrictions whose endpoints already exist
            # may cross BODY. Hoisting a new domain scan can multiply rows
            # before a selective BODY (notably multiple Abstract Factories).
            # Look through intervening pure scans for eligible restrictions,
            # crossing other source matchers only when independent of all their
            # outputs, and never crossing a scope boundary.
            end = position + 1
            crossed_outputs = set(outputs(matcher))
            selected = []
            while end < len(plan):
                candidate = plan[end]
                if candidate.kind in {"source_body", "source_type", "source_receiver"}:
                    crossed_outputs.update(outputs(candidate))
                elif candidate.kind in {"fact", "fact_union", "where", "different"}:
                    if roles(candidate) <= bound and not crossed_outputs & roles(
                        candidate
                    ):
                        selected.append(candidate)
                else:
                    break
                end += 1
            if selected:
                selected_ids = {id(node) for node in selected}
                remaining = [
                    node for node in plan[position:end] if id(node) not in selected_ids
                ]
                plan[position:end] = selected + remaining
                position += len(selected)
        bound.update(outputs(matcher))
        position += 1
    engine._source_plans[key] = (nodes, plan)
    return plan


def _positive_relation(nodes: list[Node]) -> bool:
    """Only operators whose result is unchanged by binding an exported term."""
    return all(
        node.kind in {"fact", "where", "different"}
        or node.kind == "any" and all(_positive_relation(branch) for branch in node.children)
        for node in nodes
    )


def _fact_union(node: Node) -> Node:
    """Lower alternatives with identical bindings to a reorderable fact scan.

    Keep branch order, duplicates, modality and individual fact evidence. No
    scopes or filters are moved out of branches; they retain the ANY barrier.
    """
    if node.kind != "any" or len(node.children) < 2:
        return node
    if any(len(branch) != 1 or branch[0].kind != "fact" for branch in node.children):
        return node
    clauses = tuple(branch[0].value for branch in node.children)
    endpoints = {(c.subject, c.object) for c in clauses}
    if len(endpoints) != 1 or len({c.relation for c in clauses}) == 1:
        return node
    return Node("fact_union", clauses)


def _positive_union_roles(node: Node) -> set[str] | None:
    """Conservative dependencies for distributing one independent fact over ANY."""
    roles: set[str] = set()

    def expression(expr):
        if expr.kind == "role":
            roles.add("$" + expr.value)
        for child in expr.args:
            expression(child)

    def clause(item):
        if "qualify" in item.flags:
            roles.add("$unit")
        for name in (item.role, item.alias, item.name):
            if name:
                roles.add("$" + name)
        for expr in item.expressions:
            expression(expr)
        for block in item.blocks:
            for child in block:
                clause(child)

    def visit(item):
        if item.kind == "any":
            return all(visit(child) for branch in item.children for child in branch)
        if item.kind == "fact":
            terms = (item.value.subject, item.value.object)
        elif item.kind == "where":
            terms = (item.value[0], item.value[2])
        elif item.kind == "different":
            terms = item.value
        elif item.kind == "source_body":
            pattern = item.value
            roles.add("$" + pattern.owner)
            roles.update("$" + name for name in pattern.outputs)
            for c in pattern.clauses:
                clause(c)
            return True
        else:
            return False
        roles.update(t.split(".")[0] for t in terms if _variable(t))
        return True

    return roles if visit(node) else None


def estimate_rows(
    engine: Executor, clause: Clause, bindings: dict[str, str], constraints=None
) -> int:
    """Estimate the output of a scan after its pushed-down source restrictions."""
    if constraints is not None and not constraints.allows(bindings):
        return 0
    estimate = engine.clause_size(clause, bindings)
    if constraints is None or not estimate:
        return estimate
    subject, object_ = (
        _resolve(clause.subject, bindings),
        _resolve(clause.object, bindings),
    )
    for is_subject, role in ((True, clause.subject), (False, clause.object)):
        if role in bindings:
            continue
        domain = constraints.domain(bindings, role)
        if domain is None:
            continue
        if estimate <= len(domain):
            # Preserve selectivity without probing the larger domain. Using
            # only the incumbent size here can choose a much worse join order.
            candidates = engine.candidates(clause, subject, object_)
            if len(candidates) <= len(domain):
                estimate = min(estimate, sum(
                    (fact.subject if is_subject else fact.object) in domain
                    for fact in candidates
                ))
            continue
        size = 0
        for value in domain:
            size += len(
                engine.index.rows(
                    clause.relation,
                    value if is_subject else subject,
                    object_ if is_subject else value,
                )
            )
            if size >= estimate:
                break
        estimate = min(estimate, size)
    return estimate


def _selection(engine, index, reason, estimates=()):
    if engine.profiler is not None:
        engine.profiler.select(index, reason, estimates)
    return index


def choose_next(
    engine: Executor, pending: list[Node], bindings: dict[str, str], constraints=None
) -> int:
    if engine.reference:
        return _selection(engine, 0, "author_order")
    bound = set(bindings)
    boundary = engine.pool_boundary(pending, bound)
    early = engine.ready_filter(pending[:boundary], bound)
    if early is not None:
        return _selection(engine, early, "bound_filter")
    joins = [
        index for index in range(boundary)
        if pending[index].kind in {"fact", "fact_union"}
    ]
    if not joins:
        return _selection(engine, 0, "semantic_barrier")
    if len(joins) == 1 and engine.profiler is None:
        return joins[0]
    def estimate(node):
        clauses = node.value if node.kind == "fact_union" else (node.value,)
        return sum(estimate_rows(engine, clause, bindings, constraints) for clause in clauses)

    estimates = [(index, estimate(pending[index])) for index in joins]

    def cost(item):
        index, size = item
        clause = pending[index].value
        if pending[index].kind == "fact_union":
            clause = clause[0]
        roles = {term for term in (clause.subject, clause.object) if _variable(term)}
        # Prefer correlation when cardinality ties, so an unrelated domain does
        # not introduce a Cartesian product ahead of an equally selective join.
        disconnected = bool(bound and roles and not roles & bound)
        return size, disconnected, index

    selected = min(estimates, key=cost)[0]
    return _selection(engine, selected, "estimated_cardinality", estimates)


def empty_required_relation(engine: Executor, nodes: list[Node]) -> Node | None:
    """A mandatory empty scan proves a conjunction empty before expensive work.

    Inspect only direct positive facts. An empty branch of ANY, a negated
    relation or a zero-count aggregate does not make its parent impossible.
    The index is an immutable snapshot, so this proof is independent of bindings.
    """
    key = id(nodes)
    cached = engine._empty_relations.get(key)
    if cached is not None and cached[0] is nodes:
        return cached[1]
    proof = next(
        (
            node
            for node in nodes
            if node.kind == "fact"
            and not engine.index.by_relation.get(node.value.relation)
        ),
        None,
    )
    engine._empty_relations[key] = nodes, proof
    return proof


def prune_empty_relation(engine: Executor, nodes: list[Node], input_rows: int) -> bool:
    proof = empty_required_relation(engine, nodes)
    if proof is None:
        return False
    if engine.profiler is not None:
        engine.profiler.empty_relation(proof, input_rows)
    return True
