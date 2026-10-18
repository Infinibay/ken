"""Continuation points for Python cleanup and exception-group dispatch.

Points are CFG facts, never syntax operations. A shared finalizer has one body
and a guarded continuation, so its callers cannot exchange pending exits.
"""
from collections.abc import Callable

from .model import IR, Operation


class CompletionRoutes:
    def __init__(self, graph: IR, owner: str, operations: dict[str, Operation],
                 edge: Callable[..., None], finalizers: list[Operation]) -> None:
        self.graph, self.owner, self.operations, self.edge = graph, owner, operations, edge
        self.serial = 0
        self.scopes: dict[str, tuple[str, ...]] = {}
        self.finalizers = finalizers
        self.returns: list[Callable[[Operation, str], str]] = []

    def lexical_scopes(self, point: str) -> tuple[str, ...]:
        if point in self.scopes:
            return self.scopes[point]
        op = self.operations.get(point)
        return tuple(f.id for f in sorted(self.finalizers, key=lambda f: -f.end + f.start)
                     if op is not None and f.start <= op.start and op.end <= f.end)

    def point(self, op: Operation, action: str = '', **attrs) -> str:
        self.serial += 1
        point = op.id + '::continuation-' + str(self.serial)
        self.scopes[point] = self.lexical_scopes(op.id)
        self.graph.add(self.owner, 'CFG_DISPATCH', point,
                       operation=op.id, action=action, **attrs)
        return point

    def depart(self, op: Operation, target: str) -> str:
        """Abandon only finalizers whose bodies the abrupt exit leaves."""
        abandoned = tuple(s for s in self.lexical_scopes(op.id)
                          if s not in self.lexical_scopes(target))
        if not abandoned:
            return target
        point = self.point(op, 'unwind', scopes=abandoned)
        self.edge(point, target)
        return point

    def returned(self, op: Operation, exit_id: str) -> str:
        terminal = self.point(op, 'return-complete')
        self.edge(terminal, exit_id, 'return')
        target = self.returns[-1](op, terminal) if self.returns else terminal
        evaluated = self.point(op, 'return-eval')
        self.edge(evaluated, target)
        return evaluated
