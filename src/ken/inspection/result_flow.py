"""Explain where observed result identity continues and where review must resume."""

from __future__ import annotations

from .graph import Program, location


def explain(
    program: Program, uses: list[dict], *, resolved: bool, hop: int, depth: int
) -> dict:
    """A review frontier is evidence, never an inferred ownership contract."""
    boundaries = []
    for use in uses:
        kind = use["kind"]
        if kind == "assignment":
            continue  # Local aliases are already included in the usage inventory.
        boundary = {
            key: use[key]
            for key in ("kind", "path", "line", "position")
            if use.get(key) is not None
        }
        if kind == "return":
            boundary.update(
                status="returned_identity",
                next="Inspect callers and their ownership contract.",
                followed=resolved and hop < depth,
            )
            if hop >= depth:
                boundary["stop_reason"] = "depth_limit"
            elif not resolved:
                boundary["stop_reason"] = "ambiguous_target"
        elif kind in {"argument", "receiver"}:
            call = next(
                (
                    call
                    for call in program.calls
                    if call["site"]["local_id"] == use.get("consumer")
                ),
                None,
            )
            if call is not None:
                boundary["consumer"] = location(call["site"])
                boundary["resolution"] = call["resolution"]
                boundary["targets"] = [
                    location(program.nodes[t])
                    for t in call["targets"]
                    if t in program.nodes
                ]
            elif use.get("consumer_name"):
                boundary["consumer"] = {
                    "path": use["path"],
                    "line": use["line"],
                    "name": use["consumer_name"],
                    "kind": "CALL",
                }
                boundary["resolution"] = "not_inspected"
            boundary.update(
                status="argument_boundary" if kind == "argument" else "receiver_use",
                next="Read the receiving method's contract and failure paths; ownership is not established by this use.",
            )
            if kind == "receiver" and boundary.get("consumer", {}).get("name") in {
                "close",
                "dispose",
                "release",
            }:
                boundary.update(
                    status="cleanup_candidate",
                    next="Verify this method releases the resource and runs on all required paths.",
                )
        elif kind == "operand":
            boundary.update(
                status="transformed_value",
                next="Inspect the transformation; the derived result has a different identity.",
            )
        else:
            boundary.update(
                status="local_use",
                next="Inspect this condition and the paths that follow it.",
            )
        boundaries.append(boundary)
    return {
        "identity": "observed" if uses else "unknown",
        "boundaries": boundaries,
        "ownership": "unproven",
        "inventory": "open",
        **(
            {
                "next": "Inspect the call's enclosing statement; no observed use does not prove discard or a leak."
            }
            if not boundaries
            else {}
        ),
    }
