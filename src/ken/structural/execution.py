"""Conservative lexical execution evidence; raw syntax is never removed.

Only unconditional exits in the same statement sequence prove a suffix dead.
Conditions, exception dispatch, macros and dynamic effects are not evaluated.
"""
from collections import defaultdict

from .model import IR


BEHAVIOR_RELATIONS = frozenset({
    'HAS_CALL', 'DELEGATES_TO', 'CONDITIONAL_DELEGATION', 'ITERATES_CALLS',
    'ITERATED_CALL', 'ITERATES_KEYS_CALLS', 'PASSES_SELF_TO', 'RETURNS',
    'RETURNS_SELF', 'RETURNS_LOOKUP', 'READS', 'WRITES', 'ASSIGNMENT_TARGET',
    'ASSIGNMENT_VALUE', 'GUARDS_WRITE', 'WRITES_ELEMENT', 'STORES_VALUE',
    'INSERTS_INTO', 'INSERTED_VALUE',
})
BLOCKS = {'block', 'statement_block', 'compound_statement', 'statement_list'}
ABRUPT = {'return_statement', 'return_expression', 'throw_statement',
          'throw_expression', 'raise_statement', 'break_statement',
          'continue_statement', 'break_expression', 'continue_expression'}


def lexical_execution(graph: IR, *, invalid: bool = False) -> dict[str, str]:
    if invalid:
        # Error-recovery nodes can share the same span/kind with a parent, hence
        # the same projected ID. Do not walk that possibly cyclic syntax graph.
        for op in graph.operations:
            op.attrs['execution'] = 'unknown'
        return {op.id: 'unknown' for op in graph.operations}
    operations = {op.id: op for op in graph.operations}
    children = defaultdict(list)
    roots = []
    for op in graph.operations:
        parent = operations.get(op.parent or '')
        if parent is None:
            roots.append(op)
        else:
            children[parent.id].append(op)
    for siblings in children.values():
        siblings.sort(key=lambda op: (op.start, op.end))
    status = {}
    pending = [(op, False) for op in roots]
    while pending:
        op, dead = pending.pop()
        if op.id in status:
            continue
        state = 'unknown' if invalid else 'unreachable' if dead else 'possible'
        status[op.id] = state
        op.attrs['execution'] = state
        suffix_dead = dead
        for child in children[op.id]:
            # Function declarations are hoisted in JS/TS: their bodies may run
            # even when their textual declaration follows the caller's return.
            hoisted_body = (op.native_kind == 'function_declaration' and child.role in {'body', 'parameters'}
                            and graph.entities[op.owner].attrs.get('language') in {'javascript', 'typescript'})
            pending.append((child, False if hoisted_body else suffix_dead))
            if op.native_kind in BLOCKS:
                abrupt = child.native_kind in ABRUPT
                if child.native_kind == 'expression_statement':
                    parts = [c for c in children[child.id] if 'comment' not in c.native_kind]
                    abrupt = len(parts) == 1 and parts[0].native_kind in ABRUPT
                suffix_dead |= abrupt
    for op in graph.operations:
        if op.id not in status:
            status[op.id] = 'unknown'
            op.attrs['execution'] = 'unknown'
    return status
