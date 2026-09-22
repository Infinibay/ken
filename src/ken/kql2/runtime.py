"""Snapshot-scoped expression services, domains and bounded property caching."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from functools import lru_cache

import regex  # type: ignore[import-untyped]

from ken.structural_store import Node, Store

from .body import BodyEngine
from .compiler import KINDS, TYPES, Program
from .execution_control import ExecutionControl
from .expressions import ExpressionContext
from .expressions import evaluate as evaluate_expression
from .logic import PredicateRuntime
from .semantic import (
    RELATIONS,
    RETURN_OPERAND_HOPS,
    STATEMENT_RELATIONS,
    STATEMENT_UNARY,
    UNARY_RELATIONS,
    SemanticRelations,
)
from .source_ast import RELATIONS as AST_RELATIONS
from .source_ast import SourceAST
from .syntax import Expr
from .values import UNKNOWN, ASTValue, EnumValue, OperationValue, QueryValue, is_unknown


class QueryRuntime:
    """No global caches or mutable bindings: all services belong to one snapshot."""

    def __init__(
        self,
        program: Program,
        store: Store,
        snapshot: int,
        control: ExecutionControl,
        *,
        reference: bool,
    ):
        self.store, self.snapshot, self.control = store, snapshot, control
        self.check = control.check
        self.reference = reference
        coverage = store.db.execute(
            "SELECT coverage FROM k2_snapshots WHERE snapshot_id=?", (snapshot,)
        ).fetchone()
        if coverage is None:
            raise KeyError(snapshot)
        self.coverage_complete = bool(coverage[0])
        self.domain_coverage: dict[str, bool] = {}
        self.patterns: dict[str, regex.Pattern[str]] = {}
        self.enum_domains = {
            name: tuple(EnumValue(name, member) for member in members)
            for name, members in program.enums
        }
        enum_constants = {
            f"{name}.{value.name}": value
            for name, values in self.enum_domains.items()
            for value in values
        }
        # The wrapper belongs to this instance, avoiding a class-level LRU retaining
        # runtimes/stores. Immutable snapshots make the bounded cache safe.
        self.properties = lru_cache(maxsize=1024)(store.properties)
        self.semantic = SemanticRelations(store, snapshot, self.check)
        self.ast_source = SourceAST(store, snapshot, self.check)
        self.context = ExpressionContext(
            self.domain,
            self.property_value,
            self.relation,
            self.matches,
            self.check,
            enum_constants,
            None if reference else self.candidates,
        )
        self.predicates = PredicateRuntime(
            program.predicates, self.evaluate, self.check
        )
        self.bodies = BodyEngine(
            store, snapshot, self.semantic, self.check, self.matches, self.evaluate
        )

    def evaluate(self, expression: Expr, bindings: dict[str, QueryValue]) -> QueryValue:
        return evaluate_expression(expression, bindings, self.context)

    def closed_domain(self, type_name: str) -> bool:
        if type_name not in self.domain_coverage:
            complete = self.coverage_complete
            if type_name in ("CodeNode", "Expression", "Statement"):
                complete &= self.ast_source.classified()
            if type_name in ("Parameter", "Receiver"):
                missing = self.store.db.execute(
                    """SELECT 1 FROM k2_nodes n
                    JOIN k2_snapshot_units m ON m.unit_id=n.unit_id
                    LEFT JOIN k2_properties p ON p.node_id=n.node_id AND p.key='receiver'
                    WHERE m.snapshot_id=? AND n.kind='PARAMETER'
                    AND (p.tag IS NULL OR p.tag!='Bool') LIMIT 1""",
                    (self.snapshot,),
                ).fetchone()
                complete &= missing is None
            if type_name == "Binding":
                missing = self.store.db.execute(
                    """SELECT 1 FROM k2_nodes n
                    JOIN k2_snapshot_units m ON m.unit_id=n.unit_id
                    LEFT JOIN k2_properties p ON p.node_id=n.node_id AND p.key='declared'
                    WHERE m.snapshot_id=? AND n.kind='STORAGE'
                    AND (p.tag IS NULL OR p.tag!='Bool') LIMIT 1""",
                    (self.snapshot,),
                ).fetchone()
                complete &= missing is None
            self.domain_coverage[type_name] = complete
        return self.domain_coverage[type_name]

    def matches(self, text: str, expression: Expr) -> bool:
        raw = expression.value
        if raw not in self.patterns:
            end = raw.rfind("/")
            flags = sum(
                {"i": regex.I, "m": regex.M, "s": regex.S}[f] for f in raw[end + 1 :]
            )
            self.patterns[raw] = regex.compile(raw[1:end], flags)
        self.check()
        return (
            self.patterns[raw].search(
                text,
                timeout=max(
                    0.000001, min(0.05, self.control.deadline - time.monotonic())
                ),
            )
            is not None
        )

    def domain(self, type_name: str) -> tuple[Iterator[QueryValue], bool]:
        if type_name in ("CodeNode", "Expression", "Statement"):
            return self.ast_source.scan(TYPES[type_name]), self.closed_domain(type_name)
        if type_name in self.enum_domains:
            return iter(self.enum_domains[type_name]), True
        if type_name == "Operation":
            return self.semantic.operations(), self.closed_domain(type_name)

        return self.entity_domain(
            type_name, reference=self.reference
        ), self.closed_domain(type_name)

    def entity_domain(
        self,
        type_name: str,
        *,
        name: str | None = None,
        owner: Node | None = None,
        reference: bool = False,
    ) -> Iterator[QueryValue]:
        """One domain definition for both full enumeration and candidate lookup."""
        for kind in KINDS[TYPES[type_name]]:
            for node in self.store.scan(
                self.snapshot, kind=kind, name=name, owner=owner, reference=reference
            ):
                self.check()
                if type_name in ("Parameter", "Receiver"):
                    receiver = self.properties(node).get("receiver")
                    if receiver is None or bool(receiver) != (type_name == "Receiver"):
                        continue
                if (
                    type_name == "Binding"
                    and self.properties(node).get("declared") is not True
                ):
                    continue
                yield node

    def candidates(
        self,
        type_name: str,
        role: str,
        condition: Expr,
        bindings: Mapping[str, QueryValue],
    ) -> tuple[Iterator[QueryValue], bool]:
        if type_name in self.enum_domains:
            return self.domain(type_name)
        if type_name == "Operation":
            return self.domain(type_name)
        if type_name in ("CodeNode", "Expression", "Statement"):
            return self.domain(type_name)

        # Only conjunctions constrain every satisfying witness. Never extract
        # filters from OR/NOT, which could discard a valid alternative.
        def conjuncts(expr: Expr) -> Iterator[Expr]:
            if expr.kind == "binary" and expr.value == "and":
                for arg in expr.args:
                    yield from conjuncts(arg)
            else:
                yield expr

        owner = None
        name = None
        for atom in conjuncts(condition):
            if atom.kind == "call" and atom.value == "owns":
                parent, child = (a.args[0] for a in atom.args)
                if (
                    child.kind == "role"
                    and child.value == role
                    and parent.kind == "role"
                ):
                    bound = bindings.get(parent.value)
                    if isinstance(bound, Node):
                        owner = bound
            if atom.kind == "binary" and atom.value == "==":
                for member, literal in (atom.args, atom.args[::-1]):
                    if (
                        member.kind == "member"
                        and member.value == "name"
                        and member.args[0].kind == "role"
                        and member.args[0].value == role
                        and literal.kind == "literal"
                    ):
                        decoded = json.loads(literal.value)
                        if isinstance(decoded, str):
                            name = decoded

        return self.entity_domain(
            type_name, name=name, owner=owner
        ), self.closed_domain(type_name)

    def property_value(self, node: QueryValue, name: str) -> QueryValue:
        if isinstance(node, (OperationValue, ASTValue)):
            found = getattr(node, name, UNKNOWN)
            return UNKNOWN if found is None else found
        if isinstance(node, Node):
            if name in ("type", "return_type", "type_status", "return_type_status"):
                descriptor = self.semantic.type_of(
                    node, returns=name.startswith("return_")
                )
                return (
                    ("unknown" if is_unknown(descriptor) else "known")
                    if name.endswith("status")
                    else descriptor
                )
            if name in ("name", "path", "language"):
                known = getattr(node, name)
                return UNKNOWN if known is None else known
            found = self.properties(node).get(name)
            return UNKNOWN if found is None else found
        return UNKNOWN

    def statement_relation(self, name: str, args: tuple[QueryValue, ...]) -> QueryValue:
        """Read the statement-containment facts the units publish.

        ``inside_try($statement, $protected)`` and its siblings state the nesting a
        pattern correlates -- which region holds a statement, which loop encloses it,
        which handler protects a region, where a jump targets, whether a protected
        region can be left without its finalizer overriding it, and which call a
        return hands back. An operand that is not a graph identity leaves the claim
        unknown; a fact the units do not publish makes it false.
        """

        def identity_of(value: QueryValue) -> str | None:
            if isinstance(value, str):
                return value
            local = getattr(value, "local_id", None)
            return local if isinstance(local, str) and local else None

        if name in STATEMENT_UNARY:
            relation, expected = STATEMENT_UNARY[name]
            subject = identity_of(args[0])
            if subject is None:
                return UNKNOWN
            return any(
                fact.object == expected
                for fact in self.semantic.facts(relation, subject)
            )
        relation = STATEMENT_RELATIONS[name]
        subject, target = identity_of(args[0]), identity_of(args[1])
        if subject is None or target is None:
            return UNKNOWN
        if name == "returns_operand":
            # ``returns_operand($return, $call)``: the walk starts at the call and
            # climbs the syntax chain, so the roles read in the order the claim does.
            subject, target = target, subject
            # Each hop is one enclosing construct, so the walk starts one step above
            # the call: a call never claims to return itself.
            frontier, seen = [subject], {subject}
            for _ in range(RETURN_OPERAND_HOPS):
                objects = [
                    fact.object
                    for current in frontier
                    for fact in self.semantic.facts(relation, current)
                ]
                if target in objects:
                    return True
                frontier = [value for value in objects if value not in seen]
                seen.update(frontier)
            return False
        return any(
            fact.object == target for fact in self.semantic.facts(relation, subject)
        )

    def relation(self, name: str, args: tuple[QueryValue, ...]) -> QueryValue:
        if name in STATEMENT_RELATIONS or name in STATEMENT_UNARY:
            return self.statement_relation(name, args)
        if name in AST_RELATIONS:
            return self.ast_source.relation(name, args)
        if name in RELATIONS:
            return self.semantic.call(name, args)
        if name in UNARY_RELATIONS:
            return self.semantic.unary(name, args)
        if name == "owns":
            parent, child = args
            if isinstance(parent, ASTValue) and isinstance(child, ASTValue):
                return self.ast_source.relation("contains_direct", args)
            if isinstance(parent, Node) and isinstance(child, OperationValue):
                return parent.local_id == child.owner
            if not isinstance(parent, Node) or not isinstance(child, Node):
                return UNKNOWN
            return parent.unit == child.unit and parent.local_id == child.owner
        if name == "kind_is":
            node, kind = args
            if isinstance(node, ASTValue):
                return (
                    kind == "node" or node.category == kind
                    if kind in ("node", "expression", "statement")
                    else False
                )
            if (
                not isinstance(node, Node)
                or not isinstance(kind, str)
                or kind not in KINDS
            ):
                return UNKNOWN
            if node.kind not in KINDS[kind]:
                return False
            if kind == "constructor":
                return self.property_value(node, "constructor")
            if kind in ("param", "receiver"):
                receiver = self.property_value(node, "receiver")
                return (
                    receiver
                    if is_unknown(receiver)
                    else bool(receiver) == (kind == "receiver")
                )
            return True
        return self.predicates.call(name, args)
