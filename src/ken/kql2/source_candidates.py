"""Sound source prefilters for relational scans; BODY remains the verifier.

Rules declare necessary evidence, never sufficient evidence. Missing CFG
coverage stays in the candidate domain so pruning cannot erase uncertainty.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Set
from dataclasses import dataclass
from functools import cached_property
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ken.structural.model import FactIndex
    from ken.structural.relational import Node

    from .syntax.ast import Clause as SourceClause

from .source_assignment_candidates import AssignmentCandidates
from .body_operations import operation_filter

_PREFIX_OPERATORS = frozenset(
    {
        "fact",
        "where",
        "different",
        "source_type",
        "source_receiver",
        "source_effective_field",
    }
)


@dataclass(frozen=True)
class OwnerRequirement:
    role: str
    relations: tuple[str, ...]
    place: str | None = None
    sequence_safe: bool = False


@dataclass(frozen=True)
class CallNameRequirement(OwnerRequirement):
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationRequirement(OwnerRequirement):
    kinds: frozenset[str] = frozenset()


def call_name_requirement(owner: str, clause: SourceClause) -> OwnerRequirement | None:
    from .body import name_spellings
    from .syntax import Expr

    if clause.expressions:
        return None
    for constraint in clause.blocks[0]:
        if constraint.kind == "property" and constraint.name == "name":
            value = constraint.expressions[0]
            if not isinstance(value, Expr):
                return None
            names = name_spellings(value)
            if names:
                return CallNameRequirement(
                    owner, ("ENTITY",), sequence_safe=True, names=names
                )
    return None


def call_result_requirement(
    owner: str, clause: SourceClause
) -> OwnerRequirement | None:
    if (
        not clause.expressions
        and len(clause.blocks) == 1
        and len(clause.blocks[0]) == 1
    ):
        call = clause.blocks[0][0]
        if call.kind == "call":
            return call_name_requirement(owner, call)
    return None


def insertion_requirement(owner: str, clause: SourceClause) -> OwnerRequirement:
    return OwnerRequirement(
        owner, ("INSERTS_INTO", "WRITES_ELEMENT"), "$" + clause.role
    )


# Strategies describe necessary evidence, including the meaning of each role.
# A relation tuple is a union: at least one must be witnessed in the callable.
# Register only clauses whose matcher cannot succeed (even as unknown) without
# that witness under a structured CFG. BODY remains the final verifier.
OWNER_REQUIREMENTS = MappingProxyType(
    {
        "insert": insertion_requirement,
        "call": call_name_requirement,
        "let": call_result_requirement,
    }
)


@dataclass
class OwnerDomain:
    owners: set[str]
    covered: set[str]
    uncertain: set[str]
    places: dict[str, set[str]]
    all_places: set[str]


@dataclass
class ScanConstraints:
    planner: SourceCandidatePlanner
    assignment: tuple[str, str, str] | None
    owner: OwnerRequirement | None

    def domain(self, bindings: dict[str, str], role: str) -> set[str] | None:
        if self.owner is not None and role == self.owner.role:
            return self.planner.owner_domain(self.owner).owners
        if self.owner is not None and role == self.owner.place:
            return self.planner.place_domain(self.owner, bindings)
        if self.assignment is not None:
            return self.planner.assignments.domain(self.assignment, bindings, role)
        return None

    def allows(self, bindings: dict[str, str]) -> bool:
        if self.owner is not None and self.owner.role in bindings:
            owner = bindings[self.owner.role]
            owner_domain = self.planner.owner_domain(self.owner)
            # A prebound owner may be unknown, rather than a declaration from
            # an ENTITY scan. Only covered owners can be disproved here.
            if owner in owner_domain.covered and owner not in owner_domain.owners:
                return False
        if (
            self.owner is not None
            and self.owner.place is not None
            and self.owner.place in bindings
        ):
            place = bindings[self.owner.place]
            # Non-node inputs are treated as fresh collection captures by BODY.
            # In particular, an unknown effective field must remain unknown.
            if place in self.planner.index.ir.entities:
                domain = self.planner.place_domain(self.owner, bindings)
                if domain is not None and place not in domain:
                    return False
        return self.assignment is None or self.planner.assignments.allows(
            self.assignment, bindings
        )


class SourceCandidatePlanner:
    def __init__(self, index: FactIndex, check: Callable[[], None]):
        self.index = index
        self.check = check
        self.assignments = AssignmentCandidates(index, check)
        self._domains: dict[tuple[str, ...], OwnerDomain] = {}

    def plan(
        self, nodes: list[Node], bound: Set[str] = frozenset()
    ) -> ScanConstraints | None:
        assignment = AssignmentCandidates.pattern(nodes)
        owner = self.owner_requirement(nodes, bound)
        return ScanConstraints(self, assignment, owner) if assignment or owner else None

    @staticmethod
    def owner_requirement(
        nodes: list[Node], bound: Set[str] = frozenset()
    ) -> OwnerRequirement | None:
        callables = set()
        for node in nodes:
            if node.kind == "fact":
                clause = node.value
                if clause.relation == "ENTITY" and clause.object in (
                    "CALLABLE",
                    '"CALLABLE"',
                ):
                    callables.add(clause.subject)
            elif node.kind == "source_body":
                pattern = node.value
                role = "$" + pattern.owner
                if role not in callables and role not in bound:
                    return None
                for clause in pattern.clauses:
                    strategy = OWNER_REQUIREMENTS.get(clause.kind)
                    requirement = strategy(role, clause) if strategy else None
                    if requirement is not None and (
                        len(pattern.clauses) == 1 or requirement.sequence_safe
                    ):
                        return requirement
                if pattern.clauses:
                    # Only the first clause is unconditionally entered. Later
                    # clauses may follow a terminal gap or another scope.
                    selection = operation_filter(pattern.clauses[0])
                    if selection.kinds and not selection.semantic_calls:
                        return OperationRequirement(role, (), kinds=selection.kinds)
                return None
            elif node.kind not in _PREFIX_OPERATORS:
                return None
        return None

    def owner_domain(self, requirement: OwnerRequirement) -> OwnerDomain:
        if isinstance(requirement, CallNameRequirement):
            return self.call_domain(requirement)
        if isinstance(requirement, OperationRequirement):
            return self.operation_domain(requirement)
        cached = self._domains.get(requirement.relations)
        if cached is not None:
            return cached
        subjects = defaultdict(set)
        for relation in requirement.relations:
            for fact in self.index.rows(relation):
                self.check()
                subjects[fact.subject].add(fact.object)
        witnesses = defaultdict(set)
        for subject in subjects:
            entity = self.index.ir.entities.get(subject)
            if entity is not None and entity.attrs.get("owner"):
                witnesses[entity.attrs["owner"]].update(subjects[subject])
        # Keep only the owners needed by this prerequisite, rather than a
        # second project-wide operation index. Check cancellation in batches.
        native_operations = getattr(self.index, "operations", None)
        if native_operations is not None:
            for subject in subjects:
                self.check()
                for operation in native_operations(local_id=subject):
                    witnesses[operation.owner].update(subjects[subject])
        else:
            for number, operation in enumerate(self.index.ir.operations):
                if number % 256 == 0:
                    self.check()
                if operation.id in subjects:
                    witnesses[operation.owner].update(subjects[operation.id])
        for places in witnesses.values():
            parents = {
                fact.object
                for place in places
                for fact in self.index.rows("CONTAINER", place)
            }
            places.update(parents)
        universe, covered, uncertain = self.coverage
        domain = OwnerDomain(
            uncertain | (universe & witnesses.keys()),
            covered,
            uncertain,
            dict(witnesses),
            set().union(*witnesses.values()),
        )
        self._domains[requirement.relations] = domain
        return domain

    def operation_domain(self, requirement: OperationRequirement) -> OwnerDomain:
        key = ("operation_kinds", *sorted(requirement.kinds))
        cached = self._domains.get(key)
        if cached is not None:
            return cached
        native = getattr(self.index, "operation_owners", None)
        if native is not None:
            witnesses = set(native(requirement.kinds))
        else:
            witnesses = set()
            for number, operation in enumerate(self.index.ir.operations):
                if number % 256 == 0:
                    self.check()
                if operation.kind in requirement.kinds:
                    witnesses.add(operation.owner)
        if "RETURN" in requirement.kinds:
            # Expression-bodied callables may return a nested callable without
            # an outer RETURN operation; BODY recognizes BODY_VALUE directly.
            witnesses.update(f.subject for f in self.index.rows("BODY_VALUE"))
        universe, covered, uncertain = self.call_coverage
        domain = OwnerDomain(
            uncertain | (universe & witnesses), covered, uncertain, {}, set()
        )
        self._domains[key] = domain
        return domain

    @cached_property
    def coverage(self) -> tuple[set[str], set[str], set[str]]:
        native = getattr(self.index, "source_coverage", None)
        if native is not None:
            return native()
        structured: set[str] = set()
        incomplete: set[str] = set()
        for fact in self.index.rows("CFG_STATUS"):
            (structured if fact.object == "structured" else incomplete).add(
                fact.subject
            )
        entered = {fact.subject for fact in self.index.rows("CFG_ENTRY")}
        covered = {
            owner
            for owner in (structured - incomplete) & entered
            if owner in self.index.ir.entities
        }
        universe = {
            fact.subject
            for fact in self.index.rows("ENTITY", object="CALLABLE")
            if fact.object == "CALLABLE"
        }
        uncertain = universe - covered
        return universe, covered, uncertain

    @cached_property
    def call_coverage(self) -> tuple[set[str], set[str], set[str]]:
        from .source_coverage import supports_general_walk

        native = getattr(self.index, "source_coverage", None)
        if native is not None:
            return native(general=True)
        universe, covered, _ = self.coverage
        statuses = defaultdict(list)
        for fact in self.index.rows("CFG_STATUS"):
            statuses[fact.subject].append(fact)
        entered = {fact.subject for fact in self.index.rows("CFG_ENTRY")}
        covered = covered | {
            owner
            for owner, facts in statuses.items()
            if owner in entered
            and owner in self.index.ir.entities
            and supports_general_walk(facts)
        }
        return universe, covered, universe - covered

    @cached_property
    def call_inventory(self) -> tuple[dict[str, set[str]], set[str]]:
        names: dict[str, set[str]] = defaultdict(set)
        spans = set()
        for number, entity in enumerate(self.index.ir.entities.values()):
            if number % 256 == 0:
                self.check()
            if entity.kind != "CALL":
                continue
            owner = entity.attrs.get("owner")
            if not owner:
                continue
            spans.add(
                (owner, entity.attrs.get("start_byte"), entity.attrs.get("end_byte"))
            )
            spelling = entity.attrs.get("name")
            if not spelling:
                spelling = next(
                    (
                        fact.attrs["name"]
                        for fact in self.index.rows("ENTITY", entity.id)
                        if fact.attrs.get("name")
                    ),
                    entity.name or "",
                )
            names[str(spelling)].add(owner)
        missing = set()
        for number, operation in enumerate(self.index.ir.operations):
            if number % 256 == 0:
                self.check()
            # An operation with no semantic occurrence yields unknown in BODY,
            # even under a structured CFG. Never use a missing name as a denial.
            if (
                operation.kind == "CALL"
                and (operation.owner, operation.start, operation.end) not in spans
            ):
                missing.add(operation.owner)
        return dict(names), missing

    def call_domain(self, requirement: CallNameRequirement) -> OwnerDomain:
        key = ("call_names", *requirement.names)
        cached = self._domains.get(key)
        if cached is not None:
            return cached
        universe, covered, uncertain = self.call_coverage
        native = getattr(self.index, "call_witnesses", None)
        if native is not None:
            witnesses, missing = native(requirement.names)
        else:
            names, missing = self.call_inventory
            witnesses = set().union(
                *(names.get(name, set()) for name in requirement.names)
            )
        uncertain = uncertain | (universe & missing)
        domain = OwnerDomain(
            uncertain | (universe & witnesses), covered - missing, uncertain, {}, set()
        )
        self._domains[key] = domain
        return domain

    def place_domain(
        self, requirement: OwnerRequirement, bindings: dict[str, str]
    ) -> set[str] | None:
        domain = self.owner_domain(requirement)
        owner = bindings.get(requirement.role)
        if owner is not None:
            return domain.places.get(owner, set()) if owner in domain.covered else None
        if domain.uncertain:
            return None
        return domain.all_places
