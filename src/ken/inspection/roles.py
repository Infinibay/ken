"""Explain structural roles without turning topology into semantic proof."""

from .graph import Program, location, qualname


def describe(
    program: Program, seeds: list[str], *, depth: int = 2, limit: int = 20
) -> dict:
    connected = program.connected(seeds, depth=depth)
    ordered = list(dict.fromkeys([*seeds, *sorted(connected - set(seeds))]))
    selected = set(ordered[:limit])
    identifiers = {key: i for i, key in enumerate(ordered[:limit])}
    nodes, edges = [], []
    for key in ordered[:limit]:
        node = program.nodes.get(key)
        if node is None:
            continue
        outgoing = [c for c in program.calls if c["owner"] == key]
        incoming = [c for c in program.calls if key in c["targets"]]
        resolved = [c for c in outgoing if c["resolution"] == "resolved"]
        roles = []
        if not incoming and outgoing:
            roles.append(
                {
                    "role": "entry_candidate",
                    "basis": "No incoming calls observed in this scope.",
                }
            )
        if len(outgoing) > 1:
            roles.append(
                {
                    "role": "coordinator_candidate",
                    "basis": "Invokes multiple operations.",
                }
            )
        if resolved:
            roles.append(
                {"role": "delegates", "basis": "Calls a resolved project callable."}
            )
        else:
            roles.append(
                {
                    "role": "executor_candidate",
                    "basis": "End of the observed project-call chain; external effects remain unverified.",
                }
            )
        nodes.append(
            location(node)
            | {
                "symbol": qualname(node),
                "id": identifiers[key],
                "roles": roles,
                "inference": "structural_hypothesis",
            }
        )
    for call in program.calls:
        if call["owner"] not in selected:
            continue
        destinations = [t for t in call["targets"] if t in selected]
        if destinations or not call["targets"]:
            edges.append(
                {
                    "from": identifiers[call["owner"]],
                    "to": [identifiers[t] for t in destinations],
                    "call": location(call["site"]),
                    "resolution": call["resolution"],
                }
            )
    return {
        "scope": program.scope,
        "nodes": nodes,
        "calls": edges[: limit * 3],
        "truncated": len(ordered) > limit or len(edges) > limit * 3,
        "coverage": program.coverage(),
        "claim": "Roles are hypotheses from observed calls, not proof of business responsibility or public visibility.",
    }
