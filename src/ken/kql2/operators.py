"""Streaming physical operators. Each expands one binding frame independently.

Operator construction chooses the strategy once per plan, outside the join loop.
New scan domains implement ``apply`` and are selected in ``build_operator``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from ken.structural_store import Node

from .body import BodyPattern
from .compiler import KINDS, Action, Scan
from .planning import Step
from .runtime import QueryRuntime
from .source_ast import SELECTORS as AST_SELECTORS
from .source_types import matches as matches_type
from .syntax import Expr
from .values import UNKNOWN, ASTValue, OperationValue, QueryValue, is_unknown


@dataclass(frozen=True, slots=True)
class Frame:
    bindings: dict[str, QueryValue]
    uncertain: bool = False

    def bind(self, role: str, value: QueryValue, *, uncertain: bool = False) -> Frame:
        return Frame({**self.bindings, role: value}, self.uncertain or uncertain)


class Operator(Protocol):
    def apply(self, frame: Frame) -> Iterator[Frame]: ...


@dataclass(frozen=True, slots=True)
class PropertyTest:
    name: str
    expression: Expr
    literal: QueryValue

    @classmethod
    def compile(cls, name: str, expression: Expr) -> PropertyTest:
        return cls(
            name,
            expression,
            json.loads(expression.value) if expression.kind == "literal" else None,
        )

    def matches(
        self, actual: QueryValue, runtime: QueryRuntime, *, typed: bool = False
    ) -> QueryValue:
        if actual is None or is_unknown(actual):
            return UNKNOWN
        if self.expression.kind == "regex":
            return isinstance(actual, str) and runtime.matches(actual, self.expression)
        return (
            not typed or type(actual) is type(self.literal)
        ) and actual == self.literal


class ScanOperator:
    def __init__(self, scan: Scan, runtime: QueryRuntime):
        self.scan, self.runtime = scan, runtime
        self.tests = tuple(
            PropertyTest.compile(key, expr)
            for key, expr in scan.properties
            if expr.kind != "wildcard"
        )
        self.exact = {
            test.name: test.literal
            for test in self.tests
            if test.expression.kind == "literal"
        }


class EntityScan(ScanOperator):
    def apply(self, frame: Frame) -> Iterator[Frame]:
        scan, runtime = self.scan, self.runtime
        owner = frame.bindings[scan.owner] if scan.owner else None
        existing = frame.bindings.get(scan.role)
        assert owner is None or isinstance(owner, Node)
        assert existing is None or isinstance(existing, Node)
        name = self.exact.get("name")
        assert name is None or isinstance(name, str)
        for kind in KINDS[scan.selector]:
            for node in runtime.store.scan(
                runtime.snapshot,
                kind=kind,
                name=name,
                owner=owner,
                node_id=existing.id if existing else None,
                reference=runtime.reference,
            ):
                runtime.check()
                # Most scans only need fields already on the Node. Load the property
                # inventory lazily, once, for selectors/properties that require it.
                if scan.selector in ("var", "param", "receiver", "constructor"):
                    values = runtime.properties(node)
                    required = {
                        "var": "declared",
                        "param": "receiver",
                        "receiver": "receiver",
                        "constructor": "constructor",
                    }[scan.selector]
                    actual = values.get(required)
                    if actual is None:
                        runtime.control.result.unknown_candidates += 1
                        continue
                    if scan.selector in ("param", "receiver"):
                        if bool(actual) != (scan.selector == "receiver"):
                            continue
                    elif actual is not True:
                        continue
                valid, uncertain = True, frame.uncertain
                for test in self.tests:
                    if test.name in ("type", "return_type"):
                        descriptor = runtime.semantic.type_of(
                            node, returns=test.name == "return_type"
                        )
                        truth = matches_type(descriptor, test.expression)
                    else:
                        truth = test.matches(
                            runtime.property_value(node, test.name), runtime, typed=True
                        )
                    uncertain |= is_unknown(truth)
                    if truth is False:
                        valid = False
                        break
                if valid:
                    yield frame.bind(scan.role, node, uncertain=uncertain)


class ASTScan(ScanOperator):
    def apply(self, frame: Frame) -> Iterator[Frame]:
        scan, runtime = self.scan, self.runtime
        parent = frame.bindings[scan.owner] if scan.owner else None
        if parent is not None and not isinstance(parent, ASTValue):
            raise ValueError("AST selector requires an AST parent")
        exact = {} if runtime.reference else self.exact
        kind, name = exact.get("kind"), exact.get("name")
        assert kind is None or isinstance(kind, str)
        assert name is None or isinstance(name, str)
        for node in runtime.ast_source.scan(
            scan.selector, kind=kind, name=name, parent=parent
        ):
            if scan.role in frame.bindings and frame.bindings[scan.role] != node:
                continue
            valid, uncertain = True, frame.uncertain
            for test in self.tests:
                truth = test.matches(getattr(node, test.name, UNKNOWN), runtime)
                uncertain |= is_unknown(truth)
                valid &= truth is not False
            if valid:
                yield frame.bind(scan.role, node, uncertain=uncertain)


class OperationScan(ScanOperator):
    def apply(self, frame: Frame) -> Iterator[Frame]:
        scan, runtime = self.scan, self.runtime
        parent = frame.bindings[scan.owner] if scan.owner else None
        assert parent is None or isinstance(parent, Node)
        for operation in runtime.semantic.operations(parent):
            assert isinstance(operation, OperationValue)
            if scan.role in frame.bindings and frame.bindings[scan.role] != operation:
                continue
            valid, uncertain = True, frame.uncertain
            for test in self.tests:
                truth = test.matches(getattr(operation, test.name, UNKNOWN), runtime)
                uncertain |= is_unknown(truth)
                valid &= truth is not False
            if valid:
                yield frame.bind(scan.role, operation, uncertain=uncertain)


class EnumScan(ScanOperator):
    def apply(self, frame: Frame) -> Iterator[Frame]:
        scan, runtime = self.scan, self.runtime
        for value in runtime.enum_domains[scan.selector[5:]]:
            runtime.check()
            if scan.role not in frame.bindings or frame.bindings[scan.role] == value:
                yield frame.bind(scan.role, value)


@dataclass
class ActionOperator:
    action: Action
    runtime: QueryRuntime

    def apply(self, frame: Frame) -> Iterator[Frame]:
        truth = self.runtime.evaluate(self.action.expression, frame.bindings)
        if self.action.role:
            yield frame.bind(self.action.role, truth)
        elif truth is not False:
            yield Frame(frame.bindings, frame.uncertain or is_unknown(truth))


@dataclass
class BodyOperator:
    pattern: BodyPattern
    runtime: QueryRuntime

    def apply(self, frame: Frame) -> Iterator[Frame]:
        for bindings, uncertain in self.runtime.bodies.match(
            self.pattern, frame.bindings
        ):
            yield Frame(bindings, frame.uncertain or uncertain)


def build_operator(step: Step, runtime: QueryRuntime) -> Operator:
    if isinstance(step, BodyPattern):
        return BodyOperator(step, runtime)
    if isinstance(step, Action):
        return ActionOperator(step, runtime)
    if step.selector.startswith("enum:"):
        return EnumScan(step, runtime)
    if step.selector in AST_SELECTORS:
        return ASTScan(step, runtime)
    if step.selector == "operation":
        return OperationScan(step, runtime)
    return EntityScan(step, runtime)
