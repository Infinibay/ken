"""Projection and proof grouping at the public result boundary.

No index access or operator evaluation belongs here. Evidence remains deferred
until the executor detaches it inside the storage and cancellation scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from .relational_evidence import ProofAccumulator
from .relational_ir import Row


class Match(TypedDict):
    bindings: dict[str, str]
    status: str
    unknown: list[str]
    evidence: list[Any]
    variant: str
    evidence_score: float


@dataclass
class Projection:
    matches: list[Match]
    complete: bool
    unknown: list[str]


def project_rows(
    rows: list[Row],
    exports: dict[str, str],
    *,
    evidence_mode: str,
    max_matches: int | None,
) -> Projection:
    """Project all witnesses, bounding distinct results and their proofs separately.

    Certain rows come first, so a later uncertain derivation cannot weaken a
    result. The first new binding beyond the limit marks the result incomplete;
    duplicate bindings can still contribute proofs after the limit is reached.
    """
    result = Projection([], True, [])
    groups: dict[tuple, tuple[ProofAccumulator, Match]] = {}
    ordered = sorted(
        rows, key=lambda row: (bool(row.unknown), tuple(sorted(row.bindings.items())))
    )
    for row in ordered:
        if row.unknown and evidence_mode == "strict":
            result.unknown.extend(sorted(row.unknown))
            continue
        binding = {f"${name}": row.bindings[role] for name, role in exports.items()}
        key = tuple(sorted(binding.items()))
        if key in groups:
            groups[key][0].add(row)
            continue
        if max_matches is not None and len(result.matches) >= max_matches:
            result.complete = False
            result.unknown.append("budget:max_matches")
            break
        match: Match = {
            "bindings": binding,
            "status": "unknown" if row.unknown else "structural_match",
            "unknown": sorted(row.unknown),
            "evidence": row.evidence,
            "variant": "default",
            "evidence_score": 1.0,
        }
        groups[key] = ProofAccumulator(row), match
        result.matches.append(match)
    for proofs, match in groups.values():
        match["evidence"] = proofs.finish().evidence
    return result
