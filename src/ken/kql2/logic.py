"""Stratified, demand-driven finite predicate evaluation.

Only demanded ground tuples enter a recursive component. A component iterates
until neither its answers nor its demanded tuple set changes. Recursive calls
read the current table rather than growing the Python call stack.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque
from typing import Callable

from .syntax import Expr, ParseError
from .syntax.ast import Parameter
from .values import QueryValue, Unknown, identity, is_unknown


@dataclass(frozen=True, slots=True)
class Predicate:
    name: str
    parameters: tuple[Parameter, ...]
    formula: Expr


def components(predicates: tuple[Predicate, ...]) -> tuple[tuple[str, ...], ...]:
    """Dependency SCCs; reject recursion through negation or aggregation."""
    names = {p.name for p in predicates}
    edges: dict[str, list[tuple[str, bool]]] = {name: [] for name in names}

    def visit(expr: Expr, restricted: bool = False) -> list[tuple[str, bool]]:
        restricted |= (expr.kind == 'unary' and expr.value == 'not'
                       or expr.kind == 'binary' and expr.value not in ('and', 'or')
                       or expr.kind == 'aggregate'
                       or expr.kind == 'quantifier' and expr.value == 'forall')
        result = [(expr.value, restricted)] if expr.kind == 'call' and expr.value in names else []
        for arg in expr.args:
            result.extend(visit(arg, restricted))
        return result

    for pred in predicates:
        edges[pred.name] = visit(pred.formula)
    # Iterative Kosaraju avoids both quadratic transitive-closure storage and
    # Python recursion on long dependency chains. Sorted roots keep plans stable.
    reverse: dict[str,list[str]] = {name:[] for name in names}
    for parent, children in edges.items():
        for child, _ in children:
            reverse[child].append(parent)
    seen: set[str] = set()
    finished: list[str] = []
    for name in sorted(names):
        if name in seen:
            continue
        todo = [(name,False)]
        while todo:
            current, exiting = todo.pop()
            if exiting:
                finished.append(current)
            elif current not in seen:
                seen.add(current)
                todo.append((current,True))
                todo.extend((child,False) for child,_ in edges[current] if child not in seen)
    groups: list[tuple[str, ...]] = []
    assigned: dict[str,int] = {}
    for name in reversed(finished):
        if name in assigned:
            continue
        members: list[str] = []
        pending = [name]
        while pending:
            current = pending.pop()
            if current not in assigned:
                assigned[current] = len(groups)
                members.append(current)
                pending.extend(reverse[current])
        groups.append(tuple(sorted(members)))
    for pred in predicates:
        for target, restricted in edges[pred.name]:
            if restricted and assigned[pred.name] == assigned[target]:
                raise ParseError('recursion through negation, forall or aggregation is not stratified', pred.formula.span)
    return tuple(groups)


class PredicateRuntime:
    def __init__(self, predicates: tuple[Predicate, ...],
                 evaluate: Callable[[Expr, dict[str, QueryValue]], QueryValue],
                 check: Callable[[], None]):
        self.predicates = {p.name: p for p in predicates}
        self.groups = {name: i for i, group in enumerate(components(predicates)) for name in group}
        self.evaluate = evaluate
        self.check = check
        self.active: set[int] = set()
        self.arguments: dict[tuple[str, object], tuple[QueryValue, ...]] = {}
        self.answers: dict[tuple[str, object], QueryValue] = {}
        self.pending: dict[int, deque[tuple[str, object]]] = defaultdict(deque)
        self.queued: set[tuple[str, object]] = set()
        self.dependents: dict[tuple[str, object], set[tuple[str, object]]] = defaultdict(set)
        self.current: dict[int, tuple[str, object]] = {}

    def enqueue(self, key: tuple[str, object]) -> None:
        if key not in self.queued:
            self.queued.add(key)
            self.pending[self.groups[key[0]]].append(key)

    def call(self, name: str, arguments: tuple[QueryValue, ...]) -> QueryValue:
        if any(is_unknown(arg) for arg in arguments):
            return Unknown('predicate_argument_unknown')
        key = (name, identity(arguments))
        group = self.groups[name]
        if group in self.current:
            self.dependents[key].add(self.current[group])
        new = key not in self.arguments
        if new:
            self.check()
            self.arguments[key] = arguments
            self.answers[key] = False
            self.enqueue(key)
        if group in self.active or not new:
            return self.answers[key]
        self.active.add(group)
        try:
            while self.pending[group]:
                item = self.pending[group].popleft()
                self.queued.remove(item)
                self.check()
                self.current[group] = item
                pred = self.predicates[item[0]]
                args = self.arguments[item]
                value = self.evaluate(pred.formula, {p.role: arg for p, arg in zip(pred.parameters, args)})
                # Only new knowledge schedules dependent ground tuples. This
                # avoids rescanning an entire SCC after every derived answer.
                old = self.answers[item]
                rank = lambda v: 2 if v is True else 1 if is_unknown(v) else 0
                if rank(value) > rank(old):
                    self.answers[item] = value
                    for dependent in self.dependents[item]:
                        self.enqueue(dependent)
        finally:
            self.active.remove(group)
            self.current.pop(group, None)
        return self.answers[key]
