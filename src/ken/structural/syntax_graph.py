"""Lexical control contexts, without claiming control-flow reachability."""
from .model import IR


HANDLERS = {'except_clause', 'catch_clause'}
TRIES = {'try_statement', 'try_with_resources_statement'}


def syntax_contexts(graph: IR) -> None:
    operations = {op.id: op for op in graph.operations}
    syntax_locations = {
        (graph.entities[op.owner].path, op.start, op.end, op.native_kind): op.id
        for op in graph.operations
    }
    for entity in graph.entities.values():
        if entity.kind == 'CALL':
            node = syntax_locations.get((entity.path, entity.attrs.get('start_byte', -1),
                                         entity.attrs.get('end_byte', -1), entity.attrs.get('native_kind', '')))
            if node:
                graph.add(entity.id, 'SYNTAX_NODE', node, f'{entity.path}:{entity.line}')
                current = operations[node]
                awaited = False
                for _ in range(32):
                    parent = operations.get(current.parent or '')
                    if parent is None or parent.owner != current.owner:
                        break
                    if parent.native_kind == 'expression_statement':
                        # Rust block tails produce values, unlike terminated statements.
                        if entity.attrs.get('language') != 'rust' or ';' in parent.attrs.get('tokens', []):
                            graph.add(parent.id, 'DISCARDS_RESULT', entity.id,
                                      f'{entity.path}:{entity.line}', awaited=awaited, basis='syntax')
                        break
                    if parent.native_kind not in {'parenthesized_expression', 'await', 'await_expression'}:
                        break
                    awaited |= parent.native_kind in {'await', 'await_expression'}
                    current = parent
    parents = {op.parent for op in graph.operations if op.parent}
    contexts: dict[str, tuple[str, str, str]] = {}
    for operation in graph.operations:
        # Memoized ancestor evaluation also supports operations supplied out of order.
        pending = []
        op = operation
        seen: set[str] = set()
        while op.id not in contexts and op.id not in seen:
            seen.add(op.id)
            pending.append(op)
            parent = operations.get(op.parent or '')
            if parent is None or parent.owner != op.owner:
                break
            op = parent
        for op in reversed(pending):
            parent = operations.get(op.parent or '')
            loop, handler, protected = '', '', ''
            if parent is not None and parent.owner == op.owner:
                loop, handler, protected = contexts.get(parent.id, ('', '', ''))
                graph.add(op.id, 'SYNTAX_PARENT', parent.id)
                if parent.kind == 'LOOP':
                    loop = parent.id
                if parent.native_kind in HANDLERS:
                    handler = parent.id
                if parent.native_kind in TRIES:
                    protected = parent.id if op.role == 'body' else ''
                if op.native_kind in HANDLERS and parent.native_kind in TRIES:
                    graph.add(op.id, 'HANDLER_OF', parent.id)
            contexts[op.id] = loop, handler, protected
            for relation, target in [('ENCLOSING_LOOP', loop), ('IN_HANDLER', handler), ('IN_TRY_BODY', protected)]:
                if target:
                    graph.add(op.id, relation, target)
            # Labelled continue may target an outer loop. Do not guess that target.
            if op.native_kind == 'continue_statement' and op.id not in parents and loop:
                graph.add(op.id, 'CONTINUE_TARGET', loop)
