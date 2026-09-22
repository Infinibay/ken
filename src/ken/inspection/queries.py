"""Small KQL observations; program semantics stay owned by the KQL engine."""

import json

HEADER = 'language "kql/2"; module ken.inspection; query inspect { '


def query(body: str) -> str:
    return HEADER + body + " }"


QUERIES = {
    "definitions": query("callable $f {} select $f;"),
    "calls": query("callable $owner { call $site {} } select $owner,$site;"),
    "targets": query("edge TARGET($site,$target); select $site,$target;"),
    "possible_targets": query("edge MAY_TARGET($site,$target); select $site,$target;"),
    "usages": query(
        "callable $target {} callable $owner { body { "
        "let $value=call $target {} as $site; } } "
        "usages of $value as $use {} select $owner,$target,$site,$use;"
    ),
}


def alternatives(clauses: list[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    return "either { " + " } or { ".join(clauses) + " }"


def endpoints(
    relation: str, values: list[str], *, subject: bool = False, role: str = "$site"
) -> str:
    """Bind the selected endpoint, including identities containing a pipe."""
    value = json.dumps(sorted(set(values)))
    if any("|" in item for item in values):
        return alternatives(
            [
                f"edge {relation}({json.dumps(item)},{role});"
                if subject
                else f"edge {relation}({role},{json.dumps(item)});"
                for item in sorted(set(values))
            ]
        )
    return (
        f"edge {relation}({value},{role});"
        if subject
        else f"edge {relation}({role},{value});"
    )


def neighbors(identities: list[str], *, incoming: bool, outgoing: bool) -> str:
    clauses: list[str] = []
    if incoming:
        clauses.extend(endpoints(r, identities) for r in ("TARGET", "MAY_TARGET"))
    if outgoing:
        clauses.append(endpoints("HAS_CALL", identities, subject=True))
    return query(
        alternatives(clauses) + " edge HAS_CALL($owner,$site); select $owner,$site;"
    )


def targets(sites: list[str], *, possible: bool = False) -> str:
    relation = "MAY_TARGET" if possible else "TARGET"
    selected = endpoints(relation, sites, subject=True, role="$target")
    return query(
        selected
        + f" edge {relation}($site,$target); "
        + alternatives(
            [f"where $site == {json.dumps(site)};" for site in sorted(set(sites))]
        )
        + " select $site,$target;"
    )


def usages(sites: list[str]) -> str:
    selected = endpoints("TARGET", sites, subject=True, role="$target")
    return query(
        selected
        + " edge TARGET($call,$target); edge HAS_CALL($owner,$call); "
        + alternatives(
            [f"where $call == {json.dumps(site)};" for site in sorted(set(sites))]
        )
        + " callable $target {} callable $owner {body {let $value=call $target {} as $site;}} "
        "usages of $value as $use {} select $owner,$target,$site,$use;"
    )
