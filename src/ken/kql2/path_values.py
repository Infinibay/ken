"""Local value identities on one statement-CFG route.

Unlike callable-wide may summaries, these snapshots never join exclusive arms.
They are used only for existential call-result/return and yield witnesses. Heap
effects, dynamic locals and expression-level control retain unknown provenance.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ken.structural.model import Entity, Fact, Operation
from ken.structural_store import Node
from .source_expressions import literal_boolean

Snapshot = tuple[tuple[str, str | None], ...]


class PathValues:
    """Snapshot simple local writes as a BODY walk completes each statement."""

    def __init__(self, owner: Node, locals_: Sequence[Node], entities: Mapping[str, Entity],
                 operations: Mapping[str, Operation],
                 rows: Callable[[str, str], Sequence[Fact]],
                 parts: Callable[[str], Sequence[Operation]]) -> None:
        self.entities = entities
        self.operations = operations
        self.rows = rows
        self.parts = parts
        self.by_span = {(op.start, op.end): op for op in operations.values()}
        self.children: dict[str, list[Operation]] = {}
        for op in operations.values():
            self.children.setdefault(op.parent or '', []).append(op)
        for sequence in self.children.values():
            sequence.sort(key=lambda op: op.start)
        self.locals = {node.local_id for node in locals_ if node.kind in {'STORAGE', 'PARAMETER'}}
        self.calls = {(e.attrs.get('start_byte'), e.attrs.get('end_byte')): key
                      for key, e in entities.items()
                      if e.kind == 'CALL' and e.attrs.get('owner') == owner.local_id}
        forbidden = {'global_statement', 'nonlocal_statement', 'named_expression',
                     'delete_statement', 'import_statement', 'import_from_statement',
                     'with_statement', 'ERROR'}
        dynamic = {'eval', 'exec', 'locals', 'globals', '_getframe', 'currentframe'}
        self.enabled = (owner.language == 'python'
                        and not any(op.native_kind in forbidden for op in operations.values())
                        and not any(node.kind in {'CALLABLE', 'CLASS'} for node in locals_)
                        and not any(f.object in dynamic for call in self.calls.values()
                                    for f in rows('CALLEE_NAME', call)))
        self.initial: Snapshot | None = (tuple(sorted(
            (node.local_id, node.local_id) for node in locals_ if node.kind == 'PARAMETER'
        )) if self.enabled else None)

    def resolve(self, value: str, snapshot: Snapshot) -> str | None:
        if value in self.locals:
            return dict(snapshot).get(value)
        entity = self.entities.get(value)
        if entity is not None and entity.kind in {'STORAGE', 'PARAMETER', 'MEMBER'}:
            return None
        if self.rows('LOADED_FROM', value):
            return None
        return value

    def operand(self, op: Operation, snapshot: Snapshot) -> str | None:
        operands = self.rows('RETURN_OPERAND', op.id) or self.rows('BINDING_REFERENCE', op.id)
        if len(operands) == 1:
            return self.resolve(operands[0].object, snapshot)
        if op.native_kind in {'none', 'true', 'false', 'integer', 'float', 'string',
                              'concatenated_string'}:
            return op.id
        return self.calls.get((op.start, op.end))

    def origins(self, op: Operation, snapshot: Snapshot, depth: int = 0) -> tuple[str | None, ...]:
        """Alternatives of a bare conditional alias, without executing its arms.

        Calls/writes in conditional arms need expression CFGs, so stay unknown.
        Each alternative becomes a separate environment at an assignment.
        """
        if depth > 16:
            return (None,)
        operands = self.rows('RETURN_OPERAND', op.id)
        if operands:
            return self.value_origins(operands[0].object, snapshot, depth + 1)
        if op.native_kind != 'conditional_expression':
            return (self.operand(op, snapshot),)
        children = [child for child in self.children.get(op.id, ()) if 'comment' not in child.native_kind]
        admitted = {'identifier', 'none', 'true', 'false', 'integer', 'float', 'string', 'conditional_expression'}
        if len(children) != 3 or any(child.native_kind not in admitted for child in (children[0], children[2])):
            return (None,)
        yes, condition, no = children
        literal = literal_boolean(condition, self.children)
        arms = (yes,) if literal is True else (no,) if literal is False else (yes, no)
        return tuple(dict.fromkeys(origin for arm in arms for origin in self.origins(arm, snapshot, depth + 1)))

    def value_origins(self, value: str, snapshot: Snapshot, depth: int = 0) -> tuple[str | None, ...]:
        entity = self.entities.get(value)
        if entity is not None and entity.attrs.get('native_kind') == 'conditional_expression':
            op = self.by_span.get((entity.attrs['start_byte'], entity.attrs['end_byte']))
            return self.origins(op, snapshot, depth + 1) if op is not None else (None,)
        if entity is not None and entity.attrs.get('native_kind') == 'boolean_operator':
            return (None,)
        return (self.resolve(value, snapshot),)

    def cannot_raise(self, statement: str, snapshot: Snapshot | None, depth: int = 0) -> bool:
        """A known local load/literal does not invent an exceptional route.

        In particular ``yield known_local`` only suspends; throw()/close() from
        outside the generator are not normal evaluation of that operand.
        """
        op = self.operations.get(statement)
        if op is None or snapshot is None or depth > 32:
            return False
        if op.native_kind in {'none', 'true', 'false', 'integer', 'float'}:
            return True
        if op.native_kind == 'identifier':
            return self.operand(op, snapshot) is not None
        children = [child for child in self.children.get(op.id, ()) if 'comment' not in child.native_kind]
        if op.native_kind == 'conditional_expression' and len(children) == 3:
            literal = literal_boolean(children[1], self.children)
            return (literal is not None and self.cannot_raise(
                children[0 if literal else 2].id, snapshot, depth + 1))
        if op.native_kind == 'assignment':
            right = next((child for child in children if child.role == 'right'), None)
            left = next((child for child in children if child.role == 'left'), None)
            return (left is not None and left.native_kind == 'identifier' and right is not None
                    and self.cannot_raise(right.id, snapshot, depth + 1))
        if op.native_kind in {'expression_statement', 'parenthesized_expression', 'return_statement'} or (
                op.kind == 'YIELD' and not op.attrs.get('delegated')):
            return all(self.cannot_raise(child.id, snapshot, depth + 1) for child in children)
        return False

    def advance(self, group: str, snapshot: Snapshot | None, successor: str | None = None) -> tuple[Snapshot | None, ...]:
        if snapshot is None:
            return (None,)
        environment = dict(snapshot)
        parts = self.parts(group)
        writes = [op for op in parts if self.rows('ASSIGNMENT_TARGET', op.id)]
        # Sibling writes, unpacking and indirect targets are not an evaluation
        # order proof. Forget affected locals rather than using historical flow.
        choices: tuple[str | None, ...] = (None,)
        choice_target = None
        for op in sorted(writes, key=lambda op: (op.end, -op.start)):
            targets = self.rows('ASSIGNMENT_TARGET', op.id)
            values = self.rows('ASSIGNMENT_VALUE', op.id)
            known = (len(writes) == len(targets) == len(values) == 1
                     and op.native_kind == 'assignment')
            choices = self.value_origins(values[0].object, snapshot) if known else (None,)
            for target in targets:
                if target.object in self.locals:
                    environment[target.object] = None
                    if known:
                        choice_target = target.object
        for op in parts:
            if successor is None or any(f.object == successor and f.attrs.get('kind') == 'iterate'
                                        for f in self.rows('CFG_NEXT', group)):
                for fact in self.rows('ITERATION_BINDING', op.id):
                    environment[fact.object] = None
            for fact in self.rows('PATH_INVALIDATES', op.id):
                environment[fact.object] = None
        if choice_target is not None:
            return tuple(tuple(sorted({**environment, choice_target: origin}.items())) for origin in choices)
        return (tuple(sorted(environment.items())),)
