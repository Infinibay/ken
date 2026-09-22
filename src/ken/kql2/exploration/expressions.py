"""Compile query expressions to safe callables; no eval or source execution."""

from __future__ import annotations

import json
import math
import operator

from ..values import (
    UNKNOWN,
    Unknown,
    conjunction,
    disjunction,
    identity,
    is_unknown,
    negate,
)
from .tree import PROPERTIES, SyntaxValue, contains_unknown, result_key
from ..syntax_schema import SYNTAX_RELATIONS, property_hint


class UnsupportedExploration(ValueError):
    def __init__(self, capability, span=None):
        self.capability = capability
        location = f"{span.source}:{span.start}: " if span else ""
        super().__init__(
            location + "exploration backend does not support " + capability
        )


def positive_atoms(expression):
    if expression.kind == "binary" and expression.value == "and":
        for arg in expression.args:
            yield from positive_atoms(arg)
    else:
        yield expression


def may_fail(expression):
    """Error-producing expressions are optimizer barriers, even after scans."""
    return (
        expression.kind == "regex"
        or expression.kind == "binary"
        and expression.value in {"+", "-", "*", "/", "%", "matches"}
        or expression.kind == "unary"
        and expression.value != "not"
        or any(map(may_fail, expression.args))
    )


def links(expressions):
    for expression in expressions:
        for atom in positive_atoms(expression):
            if atom.kind == "call" and atom.value in (
                "contains",
                "contains_direct",
                "owns",
            ):
                args = [a.args[0] for a in atom.args]
                if len(args) == 2 and all(a.kind == "role" for a in args):
                    yield args[0].value, args[1].value, atom.value != "contains"


def exact_properties(expression, role):
    for atom in positive_atoms(expression):
        if atom.kind == "binary" and atom.value == "==":
            for left, right in (atom.args, tuple(reversed(atom.args))):
                if (
                    left.kind == "member"
                    and left.args[0].kind == "role"
                    and left.args[0].value == role
                    and right.kind == "literal"
                ):
                    yield left.value, json.loads(right.value)


def compile_expression(expr):
    kind = expr.kind
    if kind == "literal":
        value = json.loads(expr.value)
        return lambda frame, runtime: value
    if kind == "role":
        return lambda frame, runtime: frame.get(expr.value, UNKNOWN)
    if kind == "member":
        if expr.value not in PROPERTIES:
            raise UnsupportedExploration("property " + expr.value + ". " + property_hint(expr.value), expr.span)
        source = compile_expression(expr.args[0])

        def member(frame, runtime):
            value = source(frame, runtime)
            return value.get(expr.value) if isinstance(value, SyntaxValue) else UNKNOWN

        return member
    if kind == "list":
        items = tuple(map(compile_expression, expr.args))
        return lambda frame, runtime: tuple(f(frame, runtime) for f in items)
    if kind == "unary":
        value = compile_expression(expr.args[0])
        if expr.value == "not":
            return lambda frame, runtime: negate(value(frame, runtime))
        sign = operator.neg if expr.value == "-" else operator.pos

        def unary(frame, runtime):
            found = value(frame, runtime)
            return found if is_unknown(found) else sign(found)

        return unary
    if kind == "binary":
        left = compile_expression(expr.args[0])
        if expr.value == "matches":
            pattern = expr.args[1]
            return lambda frame, runtime: runtime.regex(left(frame, runtime), pattern)
        right = compile_expression(expr.args[1])
        operation = {
            "<": operator.lt,
            ">": operator.gt,
            "<=": operator.le,
            ">=": operator.ge,
            "+": operator.add,
            "-": operator.sub,
            "*": operator.mul,
            "/": operator.truediv,
            "%": operator.mod,
        }.get(expr.value)

        def binary(frame, runtime):
            a = left(frame, runtime)
            if expr.value == "and" and a is False:
                return False
            if expr.value == "or" and a is True:
                return True
            b = right(frame, runtime)
            if expr.value == "and":
                return conjunction(a, b)
            if expr.value == "or":
                return disjunction(a, b)
            if expr.value == "in" and b == ():
                return False
            if contains_unknown(a) or contains_unknown(b):
                return a if is_unknown(a) else b if is_unknown(b) else UNKNOWN
            if expr.value in ("==", "!="):
                equal = identity(a) == identity(b)
                return equal if expr.value == "==" else not equal
            if expr.value == "in":
                return any(identity(a) == identity(item) for item in b)
            if operation is None:
                raise UnsupportedExploration("operator " + expr.value, expr.span)
            result = operation(a, b)
            if isinstance(result, float) and not math.isfinite(result):
                raise ValueError("nonfinite query result")
            return result

        return binary
    if kind == "call":
        if expr.value not in SYNTAX_RELATIONS:
            raise UnsupportedExploration(
                "relation " + expr.value,
                expr.span,
            )
        arguments = tuple(compile_expression(a.args[0]) for a in expr.args)

        def relation(frame, runtime):
            args = tuple(f(frame, runtime) for f in arguments)
            runtime.check()
            if expr.value == "kind_is":
                node, selector = args
                return (
                    (selector == "node" or node.get("category") == selector)
                    if isinstance(node, SyntaxValue)
                    else UNKNOWN
                )
            if expr.value == "stable_id":
                return args[0].local_id if isinstance(args[0], SyntaxValue) else UNKNOWN
            if expr.value == "in_directory":
                return (
                    args[1] in args[0].tree.path.split("/")[:-1]
                    if isinstance(args[0], SyntaxValue)
                    else UNKNOWN
                )
            a, b = args
            if not isinstance(a, SyntaxValue) or not isinstance(b, SyntaxValue):
                return UNKNOWN
            if a.unit != b.unit or a.revision != b.revision:
                return False
            return (
                int(b.tree.parent[b.index]) == a.index
                if expr.value in ("contains_direct", "owns")
                else a.index < b.index < int(a.tree.end[a.index])
            )

        return relation
    if kind in ("quantifier", "aggregate"):
        if expr.value not in ("exists", "forall", "count"):
            raise UnsupportedExploration("aggregate " + expr.value, expr.span)
        for p in expr.parameters:
            if p.type.name not in ("CodeNode", "Expression", "Statement"):
                raise UnsupportedExploration("domain " + p.type.name, expr.span)
        predicate = compile_expression(expr.args[0])
        projection = compile_expression(expr.args[1]) if len(expr.args) > 1 else None
        relation_hints = () if may_fail(expr) else tuple(links((expr.args[0],)))
        domains = tuple(
            (
                p.role,
                p.type.name,
                {} if may_fail(expr) else dict(exact_properties(expr.args[0], p.role)),
            )
            for p in expr.parameters
        )

        def quantify(frame, runtime):
            uncertain = not runtime.domain_closed(
                expr.parameters, relation_hints, frame
            )
            projected = set()

            def visit(position, local):
                runtime.check()
                if position == len(expr.parameters):
                    yield local
                    return
                role, selector, exact = domains[position]
                for node in runtime.scan(
                    role,
                    selector,
                    exact,
                    None,
                    relation_hints,
                    local,
                ):
                    yield from visit(position + 1, {**local, role: node})

            for local in visit(0, frame):
                truth = predicate(local, runtime)
                if truth is False:
                    continue
                if is_unknown(truth) or any(
                    isinstance(local.get(p.role), SyntaxValue)
                    and local[p.role].tree.flags[local[p.role].index] & 6
                    for p in expr.parameters
                ):
                    uncertain = True
                    continue
                if expr.value == "exists":
                    return True
                value = projection(local, runtime)
                if expr.value == "forall" and value is False:
                    return False
                if contains_unknown(value):
                    uncertain = True
                else:
                    projected.add(result_key(value))
            if uncertain:
                return Unknown("incomplete_syntax_domain")
            return len(projected) if expr.value == "count" else expr.value == "forall"

        return quantify
    raise UnsupportedExploration("expression " + kind, expr.span)
