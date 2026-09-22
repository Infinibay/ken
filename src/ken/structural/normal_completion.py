"""Bounded statement completion; no exception dispatch or runtime reachability."""
from collections import defaultdict

from .model import IR, Operation


BLOCKS = {'block', 'statement_block', 'compound_statement', 'else_clause'}
HANDLERS = {'except_clause', 'catch_clause'}
SIMPLE = {'expression_statement', 'local_variable_declaration', 'lexical_declaration',
          'variable_declaration', 'declaration', 'pass_statement', 'empty_statement',
          'assert_statement', 'assert', 'global_statement', 'nonlocal_statement',
          'import_statement', 'import_from_statement', 'delete_statement'}
ABRUPT = {'return_statement', 'throw_statement', 'raise_statement',
          'break_statement', 'continue_statement'}
SUSPENSION = {'yield', 'yield_expression', 'await', 'await_expression',
              'throw_expression', 'co_await_expression', 'co_yield_expression'}


def normal_completion(graph: IR) -> None:
    operations = {op.id: op for op in graph.operations}
    children: dict[str, list[Operation]] = defaultdict(list)
    for op in graph.operations:
        parent = operations.get(op.parent or '')
        if parent is not None and parent.owner == op.owner and 'comment' not in op.native_kind:
            children[parent.id].append(op)
    for siblings in children.values():
        siblings.sort(key=lambda op: (op.start, op.end, op.id))
    # Remaining depth is part of the key: a deep caller must not reuse a
    # shallower analysis and accidentally bypass the nesting limit.
    memo: dict[tuple[str, int], str] = {}

    def body(op: Operation) -> Operation | None:
        return next((c for c in children[op.id] if c.native_kind in BLOCKS), None)

    def plain_try(op: Operation) -> bool:
        return op.native_kind == 'try_statement' and all(
            c.role == 'body' or c.native_kind in HANDLERS for c in children[op.id])

    def expression_supported(op: Operation) -> bool:
        pending = [op]
        while pending:
            current = pending.pop()
            if current.native_kind in SUSPENSION or current.kind in {'YIELD', 'AWAIT'}:
                return False
            # Function/class bodies have a different execution owner.
            pending.extend(children[current.id])
        return True

    def completion(op: Operation, depth: int = 0) -> str:
        key = (op.id, depth)
        if key in memo:
            return memo[key]
        if depth > 64:
            return 'unsupported'
        nested = children[op.id]
        kind = op.native_kind
        language = graph.entities[op.owner].attrs.get('language')
        result = 'unsupported'
        if graph.diagnostics or language not in {'python', 'javascript', 'typescript', 'java', 'csharp', 'cpp'}:
            pass
        elif kind in ABRUPT:
            result = 'abrupt'
        elif kind in SIMPLE:
            result = 'possible' if expression_supported(op) else 'unsupported'
        elif kind in BLOCKS:
            result = 'possible'
            for child in nested:
                result = completion(child, depth + 1)
                if result != 'possible':
                    break
        elif kind in HANDLERS:
            handler_body = body(op)
            if handler_body is not None and '*' not in op.attrs.get('tokens', []):
                result = completion(handler_body, depth + 1)
        elif kind in {'if_statement', 'elif_clause'}:
            consequence = next((c for c in nested if c.role == 'consequence'), None)
            alternatives = [c for c in nested if c.role == 'alternative']
            if consequence is not None:
                arms = [completion(consequence, depth + 1)]
                for arm in alternatives:
                    if arm.native_kind == 'elif_clause':
                        branch = next((c for c in children[arm.id] if c.role == 'consequence'), None)
                        arms.append(completion(branch, depth + 1) if branch is not None else 'unsupported')
                    else:
                        arms.append(completion(arm, depth + 1))
                if not alternatives or alternatives[-1].native_kind == 'elif_clause':
                    arms.append('possible')
                condition = next((c for c in nested if c.role == 'condition'), None)
                if condition is not None and not expression_supported(condition):
                    arms.append('unsupported')
                result = 'unsupported' if 'unsupported' in arms else 'possible' if 'possible' in arms else 'abrupt'
        elif plain_try(op):
            parts = [c for c in nested if c.role == 'body' or c.native_kind in HANDLERS]
            outcomes = [completion(c, depth + 1) for c in parts]
            if outcomes:
                result = 'unsupported' if 'unsupported' in outcomes else 'possible' if 'possible' in outcomes else 'abrupt'
        memo[key] = result
        return result

    for op in graph.operations:
        if op.native_kind in {'try_statement', 'try_with_resources_statement'}:
            finalizers = [c for c in children[op.id] if c.native_kind == 'finally_clause']
            pending = list(finalizers)
            override = False
            while pending:
                current = pending.pop()
                override |= current.native_kind in ABRUPT | SUSPENSION
                pending.extend(children[current.id])
            graph.add(op.id, 'TRY_EXIT_STATUS',
                      'unsupported' if graph.diagnostics or op.native_kind == 'try_with_resources_statement'
                      else 'may-override' if override else 'no-explicit-override',
                      basis='lexical-finalizer-exits/1')
        if op.native_kind in BLOCKS | HANDLERS | {'try_statement', 'if_statement', 'elif_clause'}:
            graph.add(op.id, 'NORMAL_COMPLETION', completion(op),
                      f'{graph.entities[op.owner].path}:{op.line}', basis='statement-normal/1')
        if op.kind == 'LOOP':
            loop_body = next((c for c in children[op.id] if c.role == 'body'), None)
            if loop_body is not None:
                statements = children[loop_body.id] if loop_body.native_kind in BLOCKS else [loop_body]
                if statements:
                    graph.add(op.id, 'LOOP_BODY_TAIL', statements[-1].id,
                              f'{graph.entities[op.owner].path}:{statements[-1].line}', basis='syntax')
        if op.native_kind in HANDLERS:
            protected = operations.get(op.parent or '')
            if protected is not None and protected.owner == op.owner and plain_try(protected) and completion(op) == 'possible':
                graph.add(op.id, 'HANDLER_FALLTHROUGH', protected.id,
                          f'{graph.entities[op.owner].path}:{op.line}', basis='statement-normal/1')
