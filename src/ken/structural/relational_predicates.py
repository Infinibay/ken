"""Bounded property postings for correlated positive fact scans.

These are necessary filters only. The original WHERE still runs, including its
missing-attribute uncertainty and asymmetric alternative-string comparisons.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .query import Clause, _variable
from .relational_ir import Node, Row, ScanConstraint
from . import relational_operators

if TYPE_CHECKING:
    from .relational import Executor

PropertyPostings = tuple[dict[str, frozenset[str]], frozenset[str]]


@dataclass
class PropertyConstraint:
    role: str
    attribute: str
    other: str
    left: bool
    literal: bool


class PredicateScan:
    def __init__(self, engine: Executor, clause: Clause,
                 predicates: list[PropertyConstraint], source: ScanConstraint | None):
        self.engine, self.clause = engine, clause
        self.predicates, self.source = predicates, source
        self.owner = getattr(source, "owner", None)

    def allows(self, bindings: dict[str, str]) -> bool:
        return self.source is None or self.source.allows(bindings)

    def domain(self, bindings: dict[str, str], role: str) -> set[str] | frozenset[str] | None:
        domain = self.source.domain(bindings, role) if self.source else None
        for predicate in self.predicates:
            if predicate.role != role:
                continue
            other = self.engine.operand(predicate.other, Row(bindings))
            if other is None:
                continue  # WHERE propagates unknown, so no denial is sound.
            key = (self.clause.relation, role == self.clause.subject,
                   predicate.attribute, predicate.left)
            postings, _ = self.engine.resources.property_postings.get_or_compute(
                repr(key), lambda: self._postings(*key)
            )
            if postings is None:
                continue
            groups, missing = postings
            # WHERE compares str(left), lowercasing bools, against alternatives
            # in str(right). Do not reverse equality or normalize both sides.
            if predicate.left:
                alternatives = [str(other)] if predicate.literal else str(other).split("|")
                selected = [groups.get(value, ()) for value in alternatives]
            else:
                value = str(other).lower() if isinstance(other, bool) else str(other)
                selected = ([groups.get(value, ())] if predicate.literal else
                            [ids for spelling, ids in groups.items()
                             if value in spelling.split("|")])
            allowed = missing.union(*selected)
            domain = allowed if domain is None else domain & allowed
        return domain

    def _postings(self, relation: str, subject: bool, attribute: str,
                  left: bool) -> PropertyPostings | None:
        # Broad operation relations must not become a second project index.
        if len(self.engine.index.by_relation.get(relation, ())) > 10000:
            return None
        facts = self.engine.index.rows(relation)
        groups: dict[str, set[str]] = {}
        missing: set[str] = set()
        seen: set[str] = set()
        for fact in facts:
            self.engine.tick()
            identifier = fact.subject if subject else fact.object
            if identifier in seen:
                continue
            seen.add(identifier)
            value = self.engine.operand("$value." + attribute,
                                        Row({"$value": identifier}))
            if value is None:
                missing.add(identifier)
            else:
                spelling = str(value).lower() if left and isinstance(value, bool) else str(value)
                groups.setdefault(spelling, set()).add(identifier)
        return ({key: frozenset(ids) for key, ids in groups.items()}, frozenset(missing))


def fact_constraints(engine: Executor, node: Node, pending: list[Node],
                     bindings: dict[str, str], source: ScanConstraint | None) -> ScanConstraint | None:
    """Use only mandatory WHERE predicates before the next semantic barrier."""
    if engine.reference or node.kind != "fact" or getattr(engine, "usage_metadata", None):
        return source
    clause = node.value
    introduced = {term for term in (clause.subject, clause.object)
                  if _variable(term) and term not in bindings}
    if not introduced:
        return source
    predicates = []
    for following in pending:
        spec = relational_operators.OPERATORS.get(following.kind)
        if spec is None or spec.barrier:
            break
        if following.kind != "where":
            continue
        first, operation, second = following.value
        if operation not in {"=", "==", "literal"}:
            continue
        for term, other, left in ((first, second, True), (second, first, False)):
            role, dot, attribute = term.partition(".")
            if (dot and role in introduced and
                    (not _variable(other) or other.split(".")[0] in bindings)):
                predicates.append(PropertyConstraint(role, attribute, other, left,
                                                    operation == "literal"))
    return PredicateScan(engine, clause, predicates, source) if predicates else source
