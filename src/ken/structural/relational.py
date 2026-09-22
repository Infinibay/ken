"""Language-independent relational plans and indexed graph execution.

Both KenQL 1 and KQL 2 lower to this operator IR. No source-language parser is
called here. Alternative, dependency, path and count boundaries constrain join
reordering; missing semantic coverage is preserved as unknown evidence.
"""

from __future__ import annotations

import json
import time
from contextlib import nullcontext
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .model import Fact, FactIndex
from .query import (
    Clause,
    QueryBudget,
    QuotedTerm,
    _bind,
    _Exhausted,
    _resolve,
    _variable,
)
from .relational_resources import ExecutionResources
from .relational_evidence import FactEvidence, materialize, merge_proofs as merge_proofs
# Stable public imports for existing compilers, extensions and local snapshots.
from .relational_ir import (
    Node as Node,
    Query as Query,
    Row as Row,
    RELATIONS as RELATIONS,
    ScanConstraint,
)
from .relational_terms import compare as _compare
from .relational_profile import ExecutionProfile
from .relational_results import project_rows

if TYPE_CHECKING:
    from ken.kql2.source_execution import SourceExecutor


def _smaller_union(rows: list[Fact], buckets: Iterable[list[Fact]]) -> list[Fact]:
    """Materialize an indexed union only when it beats the incumbent scan.

    A bound join often has one row while a domain/attribute has thousands.
    Counting posting lists before copying them avoids a full scan per input.
    """
    selected = []
    size = 0
    for bucket in buckets:
        size += len(bucket)
        if size >= len(rows):
            return rows
        selected.append(bucket)
    return [fact for bucket in selected for fact in bucket]


# Relations a scoped ``not`` may read to decide whether an owner holds a subject,
# and the relations that name global entities and so are never owner-scoped.
_OWNERSHIP_RELATIONS = (
    "HAS_OPERATION",
    "HAS_PARAMETER",
    "HAS_CALL",
    "HAS_METHOD",
    "DECLARES",
)
_GLOBAL_RELATIONS = frozenset({"ENTITY", "TYPE", "INSTANCE_OF"})


class Executor:
    """One invocation owns its budget and dependency cache; no mutable global state."""

    def __init__(
        self,
        index: FactIndex,
        queries: dict[str, Query],
        budget: QueryBudget | None = None,
        evidence_mode: str = "strict",
        *,
        profile: bool = False,
        resources: ExecutionResources | None = None,
    ):
        if evidence_mode not in {"strict", "possible"}:
            raise ValueError("evidence_mode must be strict or possible")
        if resources is not None and resources.index is not index:
            raise ValueError("execution resources belong to a different FactIndex")
        self._owns_resources = resources is None
        self.resources = (
            resources if resources is not None else ExecutionResources(index)
        )
        self.profiler = ExecutionProfile() if profile else None
        self._empty_relations: dict[int, tuple[list[Node], Node | None]] = {}
        self._closure_plans: dict[int, tuple[list[Node], bool]] = {}
        self._source_executor: SourceExecutor | None = None
        self.evidence_mode = evidence_mode
        self.scope: str | None = None
        self.index = index
        self._storage_tick = getattr(index, 'heartbeat', None)
        self.queries = queries
        self.budget = budget or QueryBudget()
        self.started = time.monotonic()
        self.states = 0
        self.rows = 0
        self.cache: dict[tuple, list[Row]] = {}
        self.dependencies: set[str] = set()
        # A scoped ``not`` re-asks the same question for every candidate row: which
        # subjects does this owner hold? The answer only depends on the owner, so
        # the ownership set is computed once instead of re-reading five relations
        # per fact.
        self._owned: dict[str, set[str]] = {}
        # Selectivity of a clause shape, for join ordering only.
        self._sizes: dict[tuple, int] = {}
        self.check = None
        self.reference = False
        self._source_plans: dict[
            tuple[int, frozenset[str]], tuple[list[Node], list[Node]]
        ] = {}

    @property
    def profile(self) -> list[dict[str, Any]] | None:
        """Public diagnostics remain available after query resources are closed."""
        return self.profiler.operators if self.profiler is not None else None

    def close(self) -> None:
        """Release per-query scratch data without waiting for cyclic GC.

        Caller-owned batch resources and diagnostics remain available. The
        executor's budget/state are unchanged; close is not a query reset.
        """
        if self._source_executor is not None:
            self._source_executor.close()
            self._source_executor = None
        if hasattr(self, "_candidate_planner"):
            del self._candidate_planner
        for attribute in (
            "_source_type_semantics", "_receiver_effects", "_declaration_initializers"
        ):
            # These adapters own callbacks bound to this executor as well.
            adapter = self.__dict__.pop(attribute, None)
            close = getattr(adapter, "close", None)
            if close is not None:
                close()
        self.cache.clear()
        self._source_plans.clear()
        self._sizes.clear()
        self._empty_relations.clear()
        self._closure_plans.clear()
        self._owned.clear()
        if self._owns_resources:
            self.resources.__dict__.pop("source_view", None)

    def validate(self, root: Query) -> None:
        from .relational_validation import validate

        validate(
            root,
            self.queries,
            RELATIONS | self.index.by_relation.keys() | self.index.ir.relations,
        )

    def tick(self) -> None:
        if self._storage_tick is not None:
            self._storage_tick()
        if self.check is not None:
            self.check()
        self.states += 1
        if self.budget.max_states is not None and self.states > self.budget.max_states:
            raise _Exhausted("max_states")
        if (
            self.budget.timeout_ms is not None
            and (time.monotonic() - self.started) * 1000 >= self.budget.timeout_ms
        ):
            raise _Exhausted("timeout_ms")

    def check_storage(self) -> None:
        """Check elapsed/cancellation budget without counting SQL VM work as rows."""
        if self.check is not None:
            self.check()
        if (
            self.budget.timeout_ms is not None
            and (time.monotonic() - self.started) * 1000 >= self.budget.timeout_ms
        ):
            raise _Exhausted("timeout_ms")

    def owned_subjects(self, scope: str) -> set[str]:
        """Subjects ``scope`` owns, memoized per engine.

        ``scope`` is set only while a scoped ``not`` is evaluated, and that
        happens for very many rows against the same owner. Scanning the five
        ownership relations once per owner instead of once per fact is the
        difference between a linear and a quadratic scope check.
        """
        members = self._owned.get(scope)
        if members is None:
            members = {
                fact.object
                for relation in _OWNERSHIP_RELATIONS
                for fact in self.index.rows(relation, scope)
            }
            self._owned[scope] = members
        return members

    def candidates(
        self, clause: Clause, sres: str | None, ores: str | None
    ) -> list[Fact]:
        """The smallest index bucket that still contains every row of a clause.

        An exact attribute filter has its own bucket, so ``call(name: "x")`` no
        longer walks the entity relation to find the one call it names. The
        bucket ignores the endpoints (the caller filters those), so this only
        ever picks a candidate list, never an intersection -- every candidate
        list is a superset of the clause's rows.
        """
        native = getattr(self.index, 'candidates', None)
        if native is not None:
            return native(clause, sres, ores)
        rows = self.index.rows(clause.relation, sres, ores)

        # Finite endpoint alternatives are an indexed union, not a wildcard.
        # Source ``type`` selectors use CLASS|INTERFACE|TRAIT|STRUCT; treating
        # that as unindexed scanned every VALUE/OPERATION for each provider.
        for endpoint, resolved, is_subject in (
            (clause.subject, sres, True),
            (clause.object, ores, False),
        ):
            if (
                resolved is not None
                or isinstance(endpoint, QuotedTerm)
                or _variable(endpoint)
                or "|" not in endpoint
            ):
                continue
            alternatives = dict.fromkeys(endpoint.split("|"))
            rows = _smaller_union(
                rows,
                (
                    self.index.rows(
                        clause.relation,
                        alternative if is_subject else sres,
                        ores if is_subject else alternative,
                    )
                    for alternative in alternatives
                ),
            )
        for key, op, value in clause.attrs:
            if op not in ("=", "literal") or not value:
                continue
            # ``=`` accepts alternatives (``name: "get|Get"``), so the bucket is
            # their union. Looking up the literal "get|Get" would find nothing and
            # silently drop every row the clause had.
            rows = _smaller_union(
                rows,
                (
                    self.index.attr_rows(clause.relation, key, alternative)
                    for alternative in (
                        [value] if op == "literal" else value.split("|")
                    )
                ),
            )
        return rows

    def clause_size(self, clause: Clause, bindings: dict[str, str]) -> int:
        from .relational_planning import clause_size

        return clause_size(self, clause, bindings)

    def facts(
        self, clause: Clause, row: Row, scan_constraints: ScanConstraint | None = None
    ) -> list[Row]:
        result = []
        candidates = self.candidates(
            clause,
            _resolve(clause.subject, row.bindings),
            _resolve(clause.object, row.bindings),
        )
        if scan_constraints is not None:
            for is_subject, role in ((True, clause.subject), (False, clause.object)):
                if role in row.bindings:
                    continue
                domain = scan_constraints.domain(row.bindings, role)
                # Probing every domain member already costs at least one
                # lookup each. A smaller incumbent is cheaper to verify.
                if domain is None or len(candidates) <= len(domain):
                    continue
                candidates = _smaller_union(
                    candidates,
                    (
                        self.index.rows(
                            clause.relation,
                            value
                            if is_subject
                            else _resolve(clause.subject, row.bindings),
                            _resolve(clause.object, row.bindings)
                            if is_subject
                            else value,
                        )
                        for value in domain
                    ),
                )
        for fact in candidates:
            self.tick()
            self.rows += 1
            if self.budget.max_rows is not None and self.rows > self.budget.max_rows:
                raise _Exhausted("max_rows")
            if self.scope and clause.relation not in _GLOBAL_RELATIONS:
                if (
                    fact.subject != self.scope
                    and fact.subject not in self.owned_subjects(self.scope)
                ):
                    continue
            bindings = dict(row.bindings)
            if not _bind(clause.subject, fact.subject, bindings) or not _bind(
                clause.object, fact.object, bindings
            ):
                continue
            if not all(
                _compare(fact.attribute(k), op, value) for k, op, value in clause.attrs
            ):
                continue
            if scan_constraints is not None and not scan_constraints.allows(bindings):
                continue
            missing = set(row.unknown)
            if fact.attribute("modality") == "may" and not any(
                k == "modality" and v == "may" for k, _, v in clause.attrs
            ):
                missing.add("possible:" + clause.relation)
            result.append(
                Row(
                    bindings,
                    row.evidence + [FactEvidence(fact)],
                    missing,
                )
            )
        return result

    def closed(self, nodes: list[Node], row: Row, owner: str | None = None) -> bool:
        from .relational_closure import can_prove_closure

        if not can_prove_closure(self, nodes):
            return False
        # ENTITY filters describe members of an already closed inventory; they
        # do not require a second, global entity inventory. Keep this proof
        # local to this conjunction, so an unrelated or alternative inventory
        # cannot justify absence (nor can resolved call targets).
        entity_domains = {
            node.value.object
            for node in nodes
            if node.kind == "fact"
            and node.value.relation in {"HAS_CALL", "HAS_PARAMETER"}
            and (subject := _resolve(node.value.subject, row.bindings)) is not None
            and f"complete:{subject}:{node.value.relation}" in self.index.ir.capabilities
        }
        for node in nodes:
            if node.kind == "fact":
                clause = node.value
                if clause.relation == "ENTITY" and clause.subject in entity_domains:
                    continue
                subject = owner or _resolve(clause.subject, row.bindings)
                if (
                    subject is None
                    or f"complete:{subject}:{clause.relation}"
                    not in self.index.ir.capabilities
                ):
                    return False
            elif node.kind == "match":
                name, bindings, _ = node.value
                child = self.queries[name]
                seed = {
                    child.exports[k]: row.bindings[v]
                    for k, v in bindings.items()
                    if v in row.bindings
                }
                if not self.closed(child.nodes, Row(seed), owner):
                    return False
            for branch in node.children:
                if not self.closed(branch, row, owner):
                    return False
        return True

    def operand(self, text: str, row: Row) -> Any:
        if text.startswith("$"):
            role, _, attr = text.partition(".")
            entity_id = row.bindings[role]
            if not attr:
                return entity_id
            usage = getattr(self, "usage_metadata", {}).get(entity_id)
            if usage is not None:
                return usage.get(attr)
            entity = self.index.ir.entities.get(entity_id)
            if entity is not None and attr == "name":
                return entity.name
            if entity is not None and attr in entity.attrs:
                return entity.attrs[attr]
            facts = self.index.rows("ENTITY", entity_id) or self.index.rows(
                "OPERATION", entity_id
            )
            return facts[0].attrs.get(attr) if facts else None
        if text.startswith('"'):
            return json.loads(text)
        return text

    @staticmethod
    def where_ready(node: Node, bound: set[str]) -> bool:
        from .relational_planning import where_ready

        return where_ready(node, bound)

    def pool_boundary(self, pending: list[Node], bound: set[str]) -> int:
        from .relational_planning import pool_boundary

        return pool_boundary(self, pending, bound)

    def ready_filter(self, pending: list[Node], bound: set[str]) -> int | None:
        from .relational_planning import ready_filter

        return ready_filter(self, pending, bound)

    def source_pruned_plan(self, nodes: list[Node], initial: set[str]) -> list[Node]:
        from .relational_planning import source_pruned_plan

        return source_pruned_plan(self, nodes, initial)

    def run_nodes(self, nodes: list[Node], rows: list[Row]) -> list[Row]:
        from .relational_operators import OPERATORS
        from .relational_planning import choose_next, prune_empty_relation
        from .relational_predicates import fact_constraints

        if not self.reference and rows and prune_empty_relation(self, nodes, len(rows)):
            return []
        scan_constraints: ScanConstraint | None = None
        if not self.reference and rows and any(node.kind == "source_body" for node in nodes):
            from ken.kql2.source_candidates import SourceCandidatePlanner

            if not hasattr(self, "_candidate_planner"):
                self._candidate_planner = SourceCandidatePlanner(self.index, self.tick)
            scan_constraints = self._candidate_planner.plan(nodes, set(rows[0].bindings))
        pending = list(
            nodes
            if self.reference or not rows
            else self.source_pruned_plan(nodes, set(rows[0].bindings))
        )
        while pending and rows:
            if self.profiler is None:
                selected = choose_next(self, pending, rows[0].bindings, scan_constraints)
            else:
                with self.profiler.planning():
                    selected = choose_next(self, pending, rows[0].bindings, scan_constraints)
            node = pending.pop(selected)
            spec = OPERATORS.get(node.kind)
            if spec is None:
                raise ValueError(f"unsupported node {node.kind}")
            if spec.clears_scan_constraints:
                # A replanned BODY may already have its owner bound, with no
                # intervening fact scan on which to apply the prerequisite.
                if scan_constraints is not None:
                    rows = [row for row in rows if scan_constraints.allows(row.bindings)]
                    if not rows:
                        break
                scan_constraints = None
            operator_constraints = fact_constraints(
                self, node, pending, rows[0].bindings, scan_constraints
            )
            if self.profiler is None:
                following: list[Row] = []
                for row in rows:
                    self.tick()
                    spec.apply(self, node, row, following, operator_constraints)
                if scan_constraints is not None and node.kind != "fact":
                    following = [
                        row for row in following if scan_constraints.allows(row.bindings)
                    ]
            else:
                following = self.profiler.run(
                    self, node, spec, rows, operator_constraints, scan_constraints
                )
            rows = following
            if spec.clears_scan_constraints and not self.reference and rows:
                scan_constraints = self._candidate_planner.plan(pending, set(rows[0].bindings))
        return rows

    def execute(self, q: Query) -> dict[str, Any]:
        if q.definitions:
            self.queries = {**self.queries, **q.definitions}
        self.validate(q)
        complete = True
        reasons = []
        results = []
        try:
            execution = getattr(self.index, 'execution', None)
            with execution(self.check_storage) if execution is not None else nullcontext():
                results = self.run_nodes(q.nodes, [Row()])
        except _Exhausted as exc:
            complete = False
            reasons.append(f"budget:{exc}")
        projected = project_rows(
            results, q.exports,
            evidence_mode=self.evidence_mode,
            max_matches=self.budget.max_matches,
        )
        matches = projected.matches
        complete &= projected.complete
        reasons.extend(projected.unknown)
        try:
            # Deferred source reads still belong to the query's time and
            # cancellation budget; no handle may escape after the index closes.
            with execution(self.check_storage) if execution is not None else nullcontext():
                for match in matches:
                    self.check_storage()
                    match["evidence"] = materialize(match["evidence"])
        except _Exhausted as exc:
            complete = False
            reasons.append(f"budget:{exc}")
            matches = []
        return {
            "matches": matches,
            "complete": complete,
            "unknown": sorted(set(reasons)),
            "stats": {
                "states": self.states,
                "rows_examined": self.rows,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 3),
                "dependencies": sorted(self.dependencies),
                **(
                    {"planning_ms": round(self.profiler.planning_ms, 3)}
                    if self.profiler is not None
                    else {}
                ),
            },
        }
