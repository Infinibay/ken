"""Proof handles during search, plain evidence at the result boundary.

A join carries references to facts. Decoding their source documents is only
necessary for the bounded proofs that survive projection, not for every tuple
examined by the query. Handles never escape a completed query result.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, TypedDict

from .model import Fact
from .relational_ir import Row


class FactEvidence(Mapping[str, Any]):
    __slots__ = ("fact",)

    def __init__(self, fact: Fact) -> None:
        self.fact = fact

    def __iter__(self) -> Iterator[str]:
        return iter(("subject", "relation", "object", "source"))

    def __len__(self) -> int:
        return 4

    def __getitem__(self, key: str) -> Any:
        if key == "source":
            return self.fact.evidence
        if key in ("subject", "relation", "object"):
            return getattr(self.fact, key)
        raise KeyError(key)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FactEvidence):
            a, b = self.fact, other.fact
            if a is b:
                return True
            if (a.subject, a.relation, a.object) != (b.subject, b.relation, b.object):
                return False
            return a.same_evidence(b)
        if isinstance(other, Mapping):
            return dict(self) == other
        return NotImplemented


def materialize(value: Any) -> Any:
    """Detach public evidence from the index while it is still open."""
    if isinstance(value, Mapping):
        return {key: materialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [materialize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(materialize(item) for item in value)
    return value


class AlternativeProof(TypedDict):
    evidence: list[Any]
    unknown: list[str]


class ProofAccumulator:
    """Incremental bounded union, ordered with certain proofs first.

    Existing alternatives are already distinct and sorted. Insert only new
    witnesses instead of rebuilding and deduplicating that prefix on every row.
    The bound limits evidence, never result enumeration or certainty upgrades.
    """

    LIMIT = 16

    def __init__(self, row: Row) -> None:
        self.preferred = row
        self.alternatives: list[AlternativeProof] | None = None
        self.truncated = False

    @staticmethod
    def _proofs(row: Row) -> tuple[list[AlternativeProof], bool]:
        if len(row.evidence) == 1 and "alternatives" in row.evidence[0]:
            group = row.evidence[0]
            return group["alternatives"], group.get("truncated", False)
        return [{"evidence": row.evidence, "unknown": sorted(row.unknown)}], False

    def add(self, row: Row) -> None:
        if self.alternatives is None:
            proofs, self.truncated = self._proofs(self.preferred)
            self.alternatives = list(proofs)
        proofs, truncated = self._proofs(row)
        self.truncated |= truncated
        for proof in proofs:
            full = len(self.alternatives) == self.LIMIT
            # A later proof of the same/lower certainty cannot enter a full
            # ordered prefix. Once truncation is known, equality is irrelevant.
            outranks_last = (
                full and not proof["unknown"] and bool(self.alternatives[-1]["unknown"])
            )
            if full and self.truncated and not outranks_last:
                continue
            if proof in self.alternatives:
                continue
            if full:
                self.truncated = True
                if not outranks_last:
                    continue
                self.alternatives.pop()
            if proof["unknown"]:
                self.alternatives.append(proof)
            else:
                position = next(
                    (i for i, p in enumerate(self.alternatives) if p["unknown"]),
                    len(self.alternatives),
                )
                self.alternatives.insert(position, proof)
        if self.preferred.unknown and not row.unknown:
            self.preferred = row

    def finish(self) -> Row:
        if self.alternatives is None:
            return self.preferred
        return Row(
            self.preferred.bindings,
            [{"alternatives": self.alternatives, "truncated": self.truncated}],
            self.preferred.unknown,
        )


def merge_proofs(first: Row, second: Row) -> Row:
    """Combine derivations without mutating either input row."""
    proofs = ProofAccumulator(first)
    proofs.add(second)
    return proofs.finish()
