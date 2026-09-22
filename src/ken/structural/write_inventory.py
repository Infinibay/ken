"""Closed inventory of explicit writes, including module and captured bindings.

Counts source occurrences, not runtime executions or writes through aliases.
Unmodeled assignments/dynamic scope withhold counts for the affected file.
"""
from collections import Counter, defaultdict
from bisect import bisect_right

from .model import IR, Operation

RELATIONS = frozenset({'ASSIGNMENT_TARGET', 'ITERATION_BINDING', 'CONTAINER', 'CALLEE_NAME',
                       'INDEX', 'WRITES_ELEMENT', 'SYNTAX_NODE', 'CLEARS_COLLECTION',
                       'ITERATION_SOURCE', 'HAS_FIELD', 'READS', 'HAS_CALL', 'TARGET', 'RECEIVER'})

def explicit_write_inventory(graph: IR) -> None:
    op: Operation | None
    owner: str | None
    if graph.diagnostics:
        return
    operations = {op.id: op for op in graph.operations}
    rows = defaultdict(list)
    for fact in graph.facts:
        if fact.relation in RELATIONS:
            rows[fact.relation].append(fact)
    targets = {f.subject: f.object for f in rows['ASSIGNMENT_TARGET']}
    counts = Counter(targets.values())
    # Foreach writes its binding even without an assignment-expression node.
    counts.update(f.object for f in rows['ITERATION_BINDING'])
    indexed_locations = {f.subject for f in rows['CONTAINER']}
    opaque = set()
    for op in graph.operations:
        if ((op.kind == 'ASSIGN' and op.id not in targets)
                or op.native_kind in {'global_statement', 'nonlocal_statement', 'delete_statement', 'named_expression', 'as_pattern'}):
            opaque.add(graph.entities[op.owner].path)
        if op.id in targets:
            target = graph.entities.get(targets[op.id])
            if target is None or (target.kind not in {'STORAGE', 'PARAMETER', 'MEMBER'} and target.id not in indexed_locations):
                opaque.add(graph.entities[op.owner].path)
        if op.kind == 'UPDATE':
            # Existing lowering supplies READS/WRITES, but lacks an exact operand
            # for every native update spelling. Do not publish a closed count.
            opaque.add(graph.entities[op.owner].path)
    for f in rows['CALLEE_NAME']:
        if f.object in {'eval', 'exec', 'locals', 'globals', '_getframe', 'currentframe'}:
            opaque.add(graph.entities[f.subject].path)
    for entity in graph.entities.values():
        if entity.kind not in {'STORAGE', 'PARAMETER', 'MEMBER'}:
            continue
        graph.add(entity.id, 'STORAGE_WRITE_STATUS', 'unsupported' if entity.path in opaque else 'supported',
                  basis='explicit-source-inventory/1')
        if entity.path not in opaque:
            graph.add(entity.id, 'STORAGE_WRITE_COUNT', str(counts[entity.id]),
                      basis='explicit-source-inventory/1')

    indexes = {f.subject: f.object for f in rows['INDEX']}
    indexed = defaultdict(list)
    for f in rows['WRITES_ELEMENT']:
        if f.subject in indexes:
            op = operations.get(f.subject)
            if op is not None:
                indexed[(op.owner, f.object, indexes[f.subject])].append(op.id)
    for (owner, container, key), writes in indexed.items():
        if graph.entities[owner].path not in opaque:
            for write in set(writes):
                graph.add(write, 'INDEXED_WRITE_COUNT', str(len(set(writes))),
                          basis='same-owner-container-index/1')

    # A collection read by a loop still denotes its entry binding if the
    # callable contains no earlier explicit replacement or clearing of it.
    clears = defaultdict(list)
    syntax = {f.subject: f.object for f in rows['SYNTAX_NODE']}
    for f in rows['CLEARS_COLLECTION']:
        op = operations.get(syntax.get(f.subject, f.subject))
        if op is not None:
            clears[(op.owner, f.object)].append(op.start)
    writes_by_owner = defaultdict(list)
    for op_id, binding in targets.items():
        if op_id in operations:
            op = operations[op_id]
            writes_by_owner[(op.owner, binding)].append(op.start)
    for f in rows['ITERATION_BINDING']:
        op = operations.get(f.subject)
        if op is not None:
            writes_by_owner[(op.owner, f.object)].append(op.start)
    for f in rows['ITERATION_SOURCE']:
        loop = operations.get(f.subject)
        if loop is None or graph.entities[loop.owner].path in opaque:
            continue
        prior = writes_by_owner[(loop.owner, f.object)] + clears[(loop.owner, f.object)]
        if not any(start < loop.start for start in prior):
            graph.add(loop.id, 'ITERATION_ENTRY_SOURCE', f.object,
                      basis='no-prior-explicit-replacement-or-clear/1')

    # Only actual resolved calls and fields read by their targets are paired;
    # enumerating every method x every field would create a quadratic graph.
    fields = {f.object for f in rows['HAS_FIELD']}
    reads = defaultdict(set)
    for f in rows['READS']:
        if f.object in fields:
            reads[f.subject].add(f.object)
    call_owners = {f.object: f.subject for f in rows['HAS_CALL']}
    # Version only the receiver occurrences actually used by calls. This is a
    # lexical write inventory, not heap identity or an interprocedural effect
    # proof. A later write cannot invalidate an earlier occurrence. Comparing
    # versions prevents joining calls on opposite sides of an explicit rebind.
    binding_events = defaultdict(list)
    for op_id, binding in targets.items():
        op = operations.get(op_id)
        if op is not None:
            binding_events[(op.owner, binding)].append((op.end, op.id, False))
    for f in rows['ITERATION_BINDING']:
        op = operations.get(f.subject)
        if op is not None:
            binding_events[(op.owner, f.object)].append((op.start, op.id, True))
    for events in binding_events.values():
        events.sort()
    for f in rows['RECEIVER']:
        call = graph.entities.get(f.subject)
        owner = call_owners.get(f.subject)
        if call is None or owner is None or call.path in opaque:
            continue
        events = binding_events[(owner, f.object)]
        position = bisect_right(events, call.attrs.get('start_byte', -1), key=lambda event: event[0])
        previous = events[position - 1] if position else None
        version = previous[1] if previous else f.object
        graph.add(call.id, 'RECEIVER_BINDING_VERSION', version, *f.evidence[:1],
                  basis='explicit-receiver-write-prefix/1')
        if previous is None or previous[2]:
            graph.add(call.id, 'RECEIVER_UNREPLACED', f.object, *f.evidence[:1],
                      basis='explicit-receiver-write-prefix/1')
    for f in rows['TARGET']:
        call = graph.entities.get(f.subject)
        owner = call_owners.get(f.subject)
        if call is None or owner is None or call.path in opaque:
            continue
        for binding in reads[f.object]:
            prior = writes_by_owner[(owner, binding)] + clears[(owner, binding)]
            if not any(start < call.attrs.get('start_byte', -1) for start in prior):
                graph.add(call.id, 'CALL_ENTRY_BINDING', binding,
                          basis='no-prior-explicit-replacement-or-clear/1')
