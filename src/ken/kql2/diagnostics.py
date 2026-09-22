"""Explain suspicious query composition without changing its meaning.

These are authoring warnings, not a proof of intent or a query optimizer.
Independent domains and global absence remain valid language constructs.
"""

from __future__ import annotations

import json

from .body import BodyPattern
from .compiler import Action, Program, _roles, free_roles
from .syntax_schema import SYNTAX_SELECTORS, syntax_kinds


def _label(role):
    # Private existential/pattern aliases are compiler implementation details.
    return "$" + role.rsplit(":", 1)[-1]


def _atoms(expr):
    if expr.kind == "binary" and expr.value in ("and", "or"):
        for arg in expr.args:
            yield from _atoms(arg)
    else:
        yield expr


def _components(roles, links):
    groups = [{role} for role in sorted(roles)]
    for link in links:
        connected = [group for group in groups if group & link]
        if connected:
            groups = [group for group in groups if not group & link]
            groups.append(set().union(*connected))
    return sorted((sorted(group) for group in groups), key=lambda group: group[0])


def diagnose(program: Program) -> list[dict]:
    """Inspect compiled source scopes, including expanded patterns and branches."""
    if program.branches:
        return [
            dict(item, branch=i + 1)
            for i, branch in enumerate(program.branches)
            for item in diagnose(branch)
        ]
    if program.graph:
        return []  # Graph relations have their own compiler; no source-scope claim.
    warnings: list[dict] = []
    seen = set()

    def warn(code, message, hint, span, **details):
        key = (code, span, message)
        if key in seen:
            return
        seen.add(key)
        warnings.append(
            {
                "code": code,
                "severity": "warning",
                "message": message,
                "hint": hint,
                "span": {"source": span.source, "start": span.start, "end": span.end},
                **details,
            }
        )

    def quantifiers(expr, outer, negated=False):
        if expr.kind in ("quantifier", "aggregate"):
            local = {p.role for p in expr.parameters}
            if expr.value == "exists" and outer and not free_roles(expr) & outer:
                kind = "not exists" if negated else "exists"
                warn(
                    "uncorrelated_exists",
                    f"{kind} is global in the selected source scope; it does not test each outer capture.",
                    "If you mean a descendant of a captured node, add where contains($owner, $witness) inside the block. Keep it global only when that is the intended property.",
                    expr.span,
                    captures=sorted(map(_label, outer)),
                )
            for arg in expr.args:
                quantifiers(arg, outer | local)
            return
        for arg in expr.args:
            quantifiers(arg, outer, expr.kind == "unary" and expr.value == "not")

    roles = {scan.role for scan in program.scans}
    links = [{scan.role, scan.owner} for scan in program.scans if scan.owner]
    expressions = [*program.filters, *program.optional]
    for step in program.steps:
        if isinstance(step, BodyPattern):
            roles.update(step.outputs)
            links.append({step.owner, *step.outputs, *_roles(step.clauses)})
        elif isinstance(step, Action) and step.role:
            roles.add(step.role)
            links.append({step.role, *free_roles(step.expression)})
            expressions.append(step.expression)
    for scan in program.scans:
        expressions.extend(expr for _, expr in scan.properties)
        if scan.selector not in SYNTAX_SELECTORS:
            continue
        props = {
            key: json.loads(expr.value)
            for key, expr in scan.properties
            if expr.kind == "literal"
        }
        for key, expr in scan.properties:
            if (
                key == "kind"
                and expr.kind == "literal"
                and props[key] not in syntax_kinds()
            ):
                warn(
                    "unknown_syntax_kind",
                    f"{props[key]!r} is not a canonical syntax kind.",
                    'Use kind: "catch" for Python except clauses; use native_kind for parser-specific names. See ken kql2 --capabilities.',
                    expr.span,
                )
            if (
                key == "name"
                and props.get("kind") == "identifier"
                and props.get(key) in {"None", "True", "False", "*"}
            ):
                warn(
                    "syntax_spelling_mismatch",
                    f"An identifier named {props[key]!r} does not describe the corresponding Python literal or wildcard import.",
                    'For literals use kind: "literal"; text: "None"; (or "True"/"False"). For import * use native_kind: "wildcard_import".',
                    expr.span,
                )
    for expr in expressions:
        links.extend(free_roles(atom) for atom in _atoms(expr))
        quantifiers(expr, roles)
    groups = _components(roles, links)
    if len(groups) > 1:
        named = [[_label(role) for role in group] for group in groups]
        warn(
            "disconnected_captures",
            "Independent capture groups can form a Cartesian product. Their existence does not establish containment or ownership.",
            "If the question requires a relationship, nest direct children or add where contains($owner, $witness). Project witnesses while checking the query. Independent groups are allowed when intentional.",
            program.projection[0].span,
            groups=named,
        )
    return warnings
