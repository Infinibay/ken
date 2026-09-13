"""Explicit collection reset shapes and same-block order after an iteration.

This is lexical evidence, not termination, reachability or queue semantics.
"""
from bisect import bisect_left
from collections import defaultdict

from .model import FactIndex, IR, Operation


def collection_lifecycle(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    operations = {op.id: op for op in graph.operations}
    syntax = {f.subject: f.object for f in index.rows('SYNTAX_NODE')}
    receivers = {f.subject: f.object for f in index.rows('RECEIVER')}
    targets = {f.subject: f.object for f in index.rows('ASSIGNMENT_TARGET')}
    empty = {f.subject for f in index.rows('EMPTY_COLLECTION')}
    arguments = {f.subject for f in index.rows('ARGUMENT')}
    resets: dict[str, str] = {}
    for fact in index.rows('ASSIGNMENT_VALUE'):
        op = operations.get(fact.subject)
        if (fact.object in empty and fact.subject in targets and op is not None
                and '=' in op.attrs.get('tokens', [])):
            resets[fact.subject] = targets[fact.subject]
            graph.add(fact.subject, 'CLEARS_COLLECTION', targets[fact.subject], *fact.evidence[:1],
                      basis='empty-literal-replacement')
    for fact in index.rows('CALLEE_NAME'):
        call = graph.entities[fact.subject]
        name = 'Clear' if call.attrs.get('language') == 'csharp' else 'clear'
        if (call.attrs.get('language') in {'python', 'java', 'csharp'} and fact.object == name
                and fact.subject not in arguments and fact.subject in receivers):
            resets[fact.subject] = receivers[fact.subject]
            graph.add(fact.subject, 'CLEARS_COLLECTION', receivers[fact.subject], *fact.evidence[:1],
                      basis='collection-api-shape')
    blocks = {'block', 'statement_block', 'compound_statement'}
    wrappers = {'expression_statement', 'parenthesized_expression'}

    def statement(node: str) -> Operation | None:
        op = operations.get(node)
        for _ in range(32):
            if op is None:
                return None
            parent = operations.get(op.parent or '')
            if parent is None or parent.owner != op.owner:
                return None
            if parent.native_kind in blocks:
                return op
            if parent.native_kind not in wrappers:
                return None
            op = parent
        return None

    siblings = defaultdict(list)
    for op in graph.operations:
        parent = operations.get(op.parent or '')
        if parent is not None and parent.owner == op.owner and parent.native_kind in blocks:
            siblings[parent.id].append(op)
    positions = {}
    barriers = defaultdict(list)
    for block, items in siblings.items():
        items.sort(key=lambda o: o.start)
        for pos, op in enumerate(items):
            positions[op.id] = pos
            if op.kind in {'RETURN', 'THROW'} or op.native_kind in {'break_statement', 'continue_statement'}:
                barriers[block].append(pos)
    iterations = defaultdict(list)
    for fact in index.rows('ITERATION_SOURCE'):
        stmt = statement(fact.subject)
        if stmt is not None and stmt.id == fact.subject:
            iterations[stmt.parent].append(stmt)
    for event in resets:
        stmt = statement(syntax.get(event, event))
        if stmt is None or stmt.parent is None:
            continue
        pos = positions[stmt.id]
        stops = barriers[stmt.parent]
        stop = bisect_left(stops, pos)
        lower_bound = stops[stop - 1] if stop else -1
        for loop in iterations[stmt.parent]:
            if lower_bound < positions[loop.id] < pos:
                graph.add(event, 'AFTER_ITERATION', loop.id, f'{graph.entities[stmt.owner].path}:{stmt.line}',
                          basis='same-block-order', analysis='collection-reset/1')
