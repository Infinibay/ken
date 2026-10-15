"""Source-owned syntactic relationships for a measured retrieval experiment.

These are syntax projections, not resolved call targets, feasible execution
paths or proof of runtime effects. Reuse the existing structural operation tree.
"""
from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ken.retrieval.model import EntityKey, Span
from ken.structural.model import IR, Operation

RELATION_FIELDS = ('conditions', 'guarded_effects', 'value_relations', 'assertions', 'call_relations')
_ASSERTION = re.compile(r'\b(?:assert\w*|expect|should|require)\b', re.IGNORECASE)


@dataclass(frozen=True)
class SourceRelation:
    kind: str
    text: str
    spans: tuple[Span, ...]


def collect_relations(source: bytes, graph: IR,
                      ownership: Mapping[EntityKey, Sequence[Span]]) -> dict[EntityKey, tuple[SourceRelation, ...]]:
    """Project one matching source/operation snapshot, preserving canonical ownership."""
    newline_offsets = [i for i, char in enumerate(source) if char == 10]
    line_owners: dict[int, EntityKey] = {}
    for owner, spans in ownership.items():
        if owner.path != graph.path:
            raise ValueError('source relationship path differs from canonical ownership')
        for span in spans:
            for line in range(span.start_line, span.end_line+1):
                previous = line_owners.setdefault(line, owner)
                if previous != owner:
                    raise ValueError('source relationship owners overlap')
    operations = {op.id: op for op in graph.operations}
    children: dict[str, list[Operation]] = defaultdict(list)
    for op in graph.operations:
        if op.parent:
            children[op.parent].append(op)
    owned: dict[str, tuple[EntityKey, Span] | None] = {}
    for op in graph.operations:
        if not 0 <= op.start <= op.end <= len(source):
            raise ValueError('source operation leaves the provided bytes')
        first = bisect.bisect_left(newline_offsets, op.start)+1
        last = bisect.bisect_left(newline_offsets, max(op.start, op.end-1))+1
        operation_owner = line_owners.get(first)
        owned[op.id] = ((operation_owner, Span(first, last)) if operation_owner is not None
                       and all(line_owners.get(line) == operation_owner for line in range(first, last+1)) else None)
    rows: dict[EntityKey, list[SourceRelation]] = {owner: [] for owner in ownership}

    def text(op: Operation) -> str:
        return source[op.start:op.end].decode('utf-8', errors='replace').strip()[:2048]

    def add(op: Operation, kind: str, value: str, prefix: tuple[Span, ...] = ()) -> None:
        identity = owned[op.id]
        if identity is not None:
            owner, span = identity
            rows[owner].append(SourceRelation(kind, value, (*prefix, span)))

    for op in graph.operations:
        identity = owned[op.id]
        if identity is None:
            continue
        owner, span = identity
        if op.role == 'condition':
            add(op, 'conditions', 'condition predicate '+text(op))
        if op.role == 'parameters':
            add(op, 'value_relations', 'input parameters '+text(op))
        if op.kind in {'RETURN', 'YIELD', 'THROW', 'ASSIGN'}:
            label = {'RETURN': 'return result value ', 'YIELD': 'yield emitted value ',
                     'THROW': 'raise throw exception ', 'ASSIGN': 'assign binding value '}[op.kind]
            add(op, 'value_relations', label+text(op))
        if op.kind == 'LOOP':
            operands = {c.role: c for c in children[op.id] if c.role}
            binding = operands.get('left') or operands.get('pattern')
            iterable = operands.get('right') or operands.get('value')
            bound = owned[binding.id] if binding is not None else None
            incoming = owned[iterable.id] if iterable is not None else None
            if binding is not None and iterable is not None and bound and incoming:
                if bound[0] == owner == incoming[0]:
                    rows[owner].append(SourceRelation('value_relations',
                        'iterate element '+text(binding)+' from input iterable '+text(iterable),
                        (bound[1], incoming[1])))
        call = op.kind == 'CALL' or op.native_kind == 'macro_invocation'
        if call:
            add(op, 'call_relations', 'call expression receiver arguments '+text(op))
        callee = next((c for c in children[op.id] if c.role in {'function', 'name', 'macro'}), None)
        if op.native_kind in {'assert_statement', 'assert_expression'} or (call and callee is not None and _ASSERTION.search(text(callee))):
            add(op, 'assertions', 'assertion spelling checks expected actual '+text(op))
        if op.kind not in {'RETURN', 'YIELD', 'THROW', 'ASSIGN', 'CALL'}:
            continue
        current = op
        guard_count = 0
        # A guard applies only to operations in its lexical callable. Sharing
        # a module source owner does not make callback bodies execute there.
        for _ in range(64):
            parent = operations.get(current.parent or '')
            if parent is None or parent.owner != op.owner:
                break
            if parent.kind == 'BRANCH' and current.role in {'consequence', 'alternative'}:
                condition = next((c for c in children[parent.id] if c.role == 'condition'), None)
                predicate = owned[condition.id] if condition is not None else None
                if condition is not None and predicate and predicate[0] == owner:
                    positive = current.role == 'consequence'
                    if parent.native_kind == 'unless':
                        positive = not positive
                    polarity = 'when' if positive else 'otherwise'
                    add(op, 'guarded_effects', f'{polarity} {text(condition)} => {op.kind.lower()} {text(op)}',
                        (predicate[1],))
                    guard_count += 1
                    if guard_count == 4:
                        break
            current = parent
    return {owner: tuple(dict.fromkeys(relations)) for owner, relations in rows.items()}
