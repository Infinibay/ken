"""Statement-level structured CFG, with explicit partial coverage.

Expression evaluation and delegated injection protocols are not expanded here.
Edges describe structured source routes, not feasible runtime paths. Python
handlers branch before an atomic statement completes, so a failed RHS never
produces its normal result or write.
"""
from collections import defaultdict

from .model import IR, Operation
from .control_completions import CompletionRoutes
from .control_exceptions import handler_types, catches_close, shadowed_bindings


def structured_control(graph: IR, *, diagnostic_paths: set[str] | None = None) -> None:
    operations = {op.id: op for op in graph.operations}
    children: dict[str, list[Operation]] = defaultdict(list)
    by_owner: dict[str, list[Operation]] = defaultdict(list)
    local_bindings: dict[str, dict[str, str]] = defaultdict(dict)
    bound_references = {fact.subject for fact in graph.facts if fact.relation == 'BINDING_REFERENCE'}
    for fact in graph.facts:
        if fact.relation in {'DECLARES', 'HAS_PARAMETER'}:
            binding = graph.entities.get(fact.object)
            if binding is not None and binding.kind in {'STORAGE', 'PARAMETER'}:
                local_bindings[fact.subject][binding.name] = binding.id
    for op in graph.operations:
        by_owner[op.owner].append(op)
        parent = operations.get(op.parent or '')
        if parent is not None and parent.owner == op.owner:
            children[parent.id].append(op)
    for siblings in children.values():
        siblings.sort(key=lambda op: op.start)
    blocks = {'do','block','statement_block','compound_statement','else_clause','statement_list','body_statement','finally_clause'}
    loops = {'for','while_statement','while_expression','for_statement','for_in_statement',
             'enhanced_for_statement','for_each_statement','foreach_statement','for_expression',
             'loop_expression','do_statement','for_range_loop'}
    unsupported = {'try_statement','try_with_resources_statement','with_statement','using_statement',
                   'switch_statement','switch_expression','match_expression','match_statement',
                   'rescue','ensure','rescue_modifier','goto_statement','labeled_statement','lock_statement','synchronized_statement'}
    bindings_by_scope = shadowed_bindings(graph)
    for body in graph.operations:
        parent = operations.get(body.parent or '')
        if body.role != 'body' or parent is None or parent.kind != 'FUNCTION' or body.owner != parent.owner:
            continue
        owner = body.owner
        shadowed: set[str] = set()
        scope = owner
        while '::module' in scope:
            shadowed.update(bindings_by_scope.get(scope, ()))
            if scope.endswith('::module'):
                break
            scope = scope.rsplit('/', 1)[0]
        exit_id = owner + '::cfg-exit'
        edges: list[tuple[str,str,str]] = []
        facts: list[tuple[str,str,str]] = []
        missing = set()
        gaps: set[str] = set()
        handlers: list[tuple[str, ...]] = []
        modeled_yields: set[str] = set()

        def edge(a: str, b: str, kind: str = 'next') -> None:
            edges.append((a,b,kind))

        completion = CompletionRoutes(graph, owner, operations, edge,
                                      [op for op in by_owner[owner] if op.native_kind == 'finally_clause'])

        def may_raise(op: Operation, depth: int = 0) -> bool:
            """Conservative atomic evaluation; an unlisted expression can throw.

            This is an exceptional source route, not a type/feasibility proof.
            Only inert statements and literal operands close the inventory.
            Ordinary yield is suspension; delegated iteration can itself fail.
            """
            if depth > 64:
                return True
            literal = {'none', 'true', 'false', 'integer', 'float', 'string'}
            if op.native_kind == 'string' and any(c.native_kind == 'interpolation' for c in children[op.id]):
                return True
            if op.native_kind in literal | {'pass_statement', 'break_statement', 'continue_statement'}:
                return False
            nested = children[op.id]
            if op.native_kind in {'expression_statement', 'parenthesized_expression', 'return_statement'}:
                return any(may_raise(child, depth + 1) for child in nested)
            if op.native_kind == 'assignment':
                fields = {child.role: child for child in nested}
                return (fields.get('left') is None or fields['left'].native_kind != 'identifier'
                        or fields.get('right') is None or may_raise(fields['right'], depth + 1))
            if op.kind == 'YIELD' and not op.attrs.get('delegated'):
                return any(may_raise(child, depth + 1) for child in nested)
            if op.kind in {'BRANCH', 'LOOP'}:
                conditions = [child for child in nested if child.role == 'condition']
                return not conditions or any(may_raise(child, depth + 1) for child in conditions)
            return True

        def build(op: Operation, after: str, break_to: str | None = None,
                  continue_to: str | None = None, depth: int = 0, false_after: str | None = None) -> str:
            entry = build_statement(op, after, break_to, continue_to, depth, false_after)
            if (entry == op.id and graph.entities[owner].attrs.get('language') == 'python'
                    and op.native_kind in {'expression_statement', 'return_statement'}):
                todo, suspensions = list(children[op.id]), []
                while todo:
                    child = todo.pop()
                    if child.kind == 'YIELD':
                        suspensions.append(child)
                    else:
                        todo.extend(children[child.id])
                if len(suspensions) == 1:
                    suspension = suspensions[0]
                    modeled_yields.add(suspension.id)
                    missing.add('generator-resumption')
                    graph.add(owner, 'CFG_DISPATCH', op.id, operation=op.id,
                              action='suspend', suspension=suspension.id,
                              delegated=bool(suspension.attrs.get('delegated')))
                    targets = handlers[-1] if handlers and handlers[-1] else (exit_id,)
                    for target in targets:
                        edge(op.id, completion.depart(op, target), 'inject-throw')
                        edge(op.id, completion.depart(op, target), 'inject-close')
            if (handlers and handlers[-1] and entry == op.id
                    and graph.entities[owner].attrs.get('language') == 'python'
                    and op.kind != 'TRY'):
                if may_raise(op):
                    dispatch = op.id + '::exception-dispatch'
                    if op.kind == 'LOOP':
                        # Re-evaluating a condition / advancing an iterator can
                        # fail after a completed iteration too.
                        edges[:] = [(a, dispatch if b == op.id else b, kind)
                                    for a, b, kind in edges]
                    graph.add(owner, 'CFG_DISPATCH', dispatch, operation=op.id)
                    edge(dispatch, entry, 'normal')
                    for handler in handlers[-1]:
                        edge(dispatch, completion.depart(op, handler), 'exception')
                    return dispatch
            return entry

        def build_statement(op: Operation, after: str, break_to: str | None = None,
                  continue_to: str | None = None, depth: int = 0, false_after: str | None = None) -> str:
            if depth > 64:
                missing.add('nesting-limit')
                return after
            nested = children[op.id]
            fields = {c.role:c for c in nested if c.role}
            language = graph.entities[owner].attrs.get('language')
            if op.native_kind == 'expression_statement' and len(nested) == 1 and nested[0].native_kind in loops | {'if_expression','return_expression','break_expression','continue_expression'}:
                return build(nested[0],after,break_to,continue_to,depth+1)
            if op.native_kind in blocks:
                entry = after
                for child in reversed(nested):
                    if 'comment' not in child.native_kind:
                        entry = build(child,entry,break_to,continue_to,depth+1)
                return entry
            if op.native_kind in {'if_modifier','if_statement','if_expression','elif_clause'}:
                condition = fields.get('condition')
                if condition is not None and condition.native_kind == 'empty_statement':
                    condition = None
                if condition is not None:
                    facts.append((op.id,'CONTROL_CONDITION',condition.id))
                alternatives = [c for c in nested if c.role == 'alternative']
                alternate = false_after if false_after is not None else after
                for arm in reversed(alternatives):
                    alternate = build(arm, after, break_to, continue_to, depth+1,
                                      alternate if arm.native_kind == 'elif_clause' else None)
                consequence = fields.get('consequence')
                if consequence is None:
                    missing.add('branch-grammar')
                    return after
                yes = build(consequence,after,break_to,continue_to,depth+1)
                edge(op.id,yes,'true'); edge(op.id,alternate,'false')
                return op.id
            if op.native_kind in loops:
                loop_body = fields.get('body')
                if loop_body is None:
                    missing.add('loop-grammar')
                    return after
                language = graph.entities[owner].attrs.get('language')
                clause = next((c for c in nested if c.native_kind in {'for_clause','range_clause'}), None)
                if clause is not None:
                    fields.update({c.role:c for c in children[clause.id] if c.role})
                iterable = fields.get('right') or fields.get('value') or fields.get('iterable')
                foreach = (op.native_kind in {'for','for_in_statement','enhanced_for_statement','for_each_statement','foreach_statement','for_expression','for_range_loop'}
                           or op.native_kind == 'for_statement' and language == 'python'
                           or clause is not None and clause.native_kind == 'range_clause')
                condition = fields.get('condition')
                if condition is not None and condition.native_kind == 'empty_statement':
                    condition = None
                if condition is not None:
                    facts.append((op.id,'CONTROL_CONDITION',condition.id))
                if iterable is not None and foreach:
                    facts.append((op.id,'CONTROL_ITERABLE',iterable.id))
                normal_exit = after
                for arm in reversed([c for c in nested if c.role == 'alternative']):
                    normal_exit = build(arm,normal_exit,break_to,continue_to,depth+1)
                update = fields.get('update') or fields.get('increment')
                back = build(update,op.id,after,op.id,depth+1) if update is not None else op.id
                entry = build(loop_body,back,after,back,depth+1)
                facts.append((op.id,'CONTROL_BODY',loop_body.id))
                edge(op.id,entry,'iterate' if foreach else 'true')
                # A C-style for(;;) or Rust loop has no normal false edge.
                if foreach or condition is not None:
                    edge(op.id,normal_exit,'exhausted' if foreach else 'false')
                elif op.native_kind not in {'for_statement','loop_expression'}:
                    missing.add('loop-condition')
                initializer = fields.get('initializer')
                start = entry if op.native_kind == 'do_statement' else op.id
                return build(initializer,start,break_to,continue_to,depth+1) if initializer is not None else start
            if op.native_kind in {'break','break_statement','continue_statement','break_expression','continue_expression'}:
                is_break = op.native_kind.startswith('break')
                target = break_to if is_break else continue_to
                if target is None or any('comment' not in c.native_kind for c in nested):
                    missing.add('label-or-control-target')
                else:
                    edge(op.id,completion.depart(op, target),'break' if is_break else 'continue')
                return op.id
            if language == 'python' and op.native_kind == 'with_statement':
                resource_body = fields.get('body')
                if resource_body is not None:
                    entry = build(resource_body, after, break_to, continue_to, depth+1)
                    edge(op.id, entry, 'enter')
                    return op.id
            if language == 'python' and op.native_kind == 'try_statement':
                protected = fields.get('body')
                finalizer = next((c for c in nested if c.native_kind == 'finally_clause'), None)
                arms = [c for c in nested if c.native_kind == 'except_clause']
                starred = bool(arms) and all('*' in arm.attrs.get('tokens', ()) for arm in arms)
                opaque_handler = False
                for arm in arms:
                    todo = [c for c in children[arm.id] if c.native_kind != 'block']
                    while todo:
                        header = todo.pop()
                        opaque_handler |= header.kind == 'CALL'
                        todo.extend(children[header.id])
                if protected is None or opaque_handler:
                    missing.add(op.native_kind)
                    gaps.add(op.id)
                    edge(op.id, after, 'uncovered')
                    return op.id
                missing.add('exception-dispatch')
                outer_handlers = handlers[-1] if handlers and handlers[-1] else (exit_id,)
                normal_after = after
                routed_handlers = outer_handlers
                routed_break, routed_continue = break_to, continue_to
                if finalizer is not None:
                    missing.add('completion-dispatch')
                    leave = completion.point(finalizer, 'finally-leave', scope=finalizer.id)
                    final_entry = build(finalizer, leave, break_to, continue_to, depth+1)
                    destinations: dict[str, str] = {}

                    def finalize(target: str) -> str:
                        if target not in destinations:
                            continuation = completion.depart(finalizer, target)
                            enter = completion.point(op, 'finally-enter', scope=finalizer.id, target=continuation)
                            edge(enter, final_entry)
                            edge(leave, continuation, 'resume')
                            destinations[target] = enter
                        return destinations[target]

                    normal_after = finalize(after)
                    routed_handlers = tuple(finalize(target) for target in outer_handlers)
                    routed_break = finalize(break_to) if break_to is not None else None
                    routed_continue = finalize(continue_to) if continue_to is not None else None
                    outer_return = completion.returns[-1] if completion.returns else None
                    completion.returns.append(lambda ret, terminal: finalize(
                        outer_return(ret, terminal) if outer_return is not None else terminal))

                # Handlers execute outside their own protected exception inventory.
                # except* records raised subgroups and visits the remaining arms
                # before deciding between normal continuation and propagation.
                handler_after = normal_after
                star_entry = None
                if starred:
                    missing.add('exception-group')
                    merge = completion.point(op, 'star-exit', scope=op.id, normal=normal_after)
                    edge(merge, normal_after, 'handled')
                    for target in routed_handlers:
                        edge(merge, target, 'unhandled')
                    handler_after = merge
                entries = []
                close_order: list[str] = []
                catches_all = False
                for arm in reversed(arms) if starred else arms:
                    arm_body = next((c for c in children[arm.id] if c.native_kind == 'block'), None)
                    if arm_body is None:
                        continue
                    types = handler_types(arm, children, bound_references, shadowed)
                    aliases = [c for c in children[arm.id] if c.native_kind == 'as_pattern']
                    names = [name.attrs.get('text') for alias in aliases
                             for target in children[alias.id] if target.role == 'alias'
                             for name in children[target.id]]
                    invalidated = [local_bindings[owner][name] for name in names if name in local_bindings[owner]]

                    def cleanup(label: str, target: str | None) -> str | None:
                        if not invalidated or target is None:
                            return target
                        boundary = completion.point(arm)
                        edge(boundary, target)
                        for binding in invalidated:
                            graph.add(boundary, 'PATH_INVALIDATES', binding)
                        return boundary

                    next_arm = handler_after
                    failures = routed_handlers
                    if starred:
                        failed = completion.point(arm, 'star-raise', scope=op.id)
                        edge(failed, next_arm)
                        failures = (failed,)
                    handlers.append(tuple(cleanup('raise', target) or target for target in failures))
                    cleaned_after = cleanup('exit', next_arm)
                    assert cleaned_after is not None
                    handler_entry = build(arm_body, cleaned_after,
                                          cleanup('break', routed_break), cleanup('continue', routed_continue), depth+1)
                    handlers.pop()
                    if invalidated:
                        boundary = completion.point(arm)
                        edge(boundary, handler_entry)
                        for binding in invalidated:
                            graph.add(boundary, 'PATH_INVALIDATES', binding)
                        handler_entry = boundary
                    if starred:
                        matched = completion.point(arm, 'star-match', scope=op.id, types=types or ())
                        graph.add(owner, 'CFG_DISPATCH', arm.id, operation=arm.id, action='star-header',
                                  close=catches_close(types), types=types or (), match=matched)
                        edge(matched, handler_entry)
                        edge(arm.id, matched, 'handler')
                        edge(arm.id, next_arm, 'skip')
                        handler_after = arm.id
                    else:
                        graph.add(owner, 'CFG_DISPATCH', arm.id, operation=arm.id,
                                  action='handler', close=catches_close(types),
                                  close_blocked='yes' in close_order, close_uncertain='unknown' in close_order)
                        close_order.append(catches_close(types))
                        edge(arm.id, handler_entry, 'handler')
                        entries.append(arm.id)
                        if not any(c.role == 'value' for c in children[arm.id]):
                            catches_all = True
                            break
                if starred:
                    star_entry = completion.point(op, 'star-enter', scope=op.id)
                    edge(star_entry, handler_after)
                    entries = [star_entry]
                handlers.append(routed_handlers)
                for arm in reversed([c for c in nested if c.native_kind == 'else_clause']):
                    normal_after = build(arm, normal_after, routed_break, routed_continue, depth+1)
                handlers.pop()
                propagated = routed_handlers
                if not starred and close_order and not catches_all:
                    guarded = []
                    acceptance = 'no' if 'yes' in close_order else 'unknown' if 'unknown' in close_order else 'yes'
                    for target in propagated:
                        boundary = completion.point(op, 'propagate', close=acceptance)
                        edge(boundary, target)
                        guarded.append(boundary)
                    propagated = tuple(guarded)
                handlers.append(tuple(entries) + (() if starred or catches_all else propagated))
                normal = build(protected, normal_after, routed_break, routed_continue, depth+1)
                handlers.pop()
                if finalizer is not None:
                    completion.returns.pop()
                edge(op.id, normal, 'normal')
                return op.id
            if op.native_kind in {'raise_statement', 'throw_statement'}:
                for target in handlers[-1] if language == 'python' and handlers and handlers[-1] else (exit_id,):
                    edge(op.id, completion.depart(op, target), 'raise')
                return op.id
            if op.kind == 'RETURN' or op.kind == 'YIELD' and 'break' in op.attrs.get('tokens',()):
                target = (completion.returned(op, exit_id) if language == 'python' and completion.finalizers
                          else exit_id)
                edge(op.id, target, 'return')
                return op.id
            if op.native_kind in unsupported or op.kind in {'TRY','THROW','YIELD','AWAIT','RESOURCE_SCOPE','MATCH'}:
                missing.add(op.native_kind)
            edge(op.id,after)
            return op.id

        entry = build(body,exit_id)
        # Report expression-level effects even when wrapped in an atomic statement.
        for op in by_owner[owner]:
            if (graph.entities[owner].attrs.get('language') == 'python'
                    and op.kind == 'YIELD' and op.id not in modeled_yields):
                missing.add('suspension-expression')
            if op.kind in {'YIELD','AWAIT','THROW'}:
                missing.add(op.native_kind)
        graph.add(owner,'CFG_ENTRY',entry,basis='structured-syntax')
        graph.add(owner,'CFG_EXIT',exit_id,basis='structured-syntax')
        for a,b,kind in sorted(set(edges)):
            graph.add(a,'CFG_NEXT',b,kind=kind,basis='structured-syntax')
            if kind == 'next':
                graph.add(a,'CFG_FALLTHROUGH',b,basis='structured-syntax')
        for a,r,b in facts:
            graph.add(a,r,b,basis='syntax')
        diagnostics = (bool(graph.diagnostics) if diagnostic_paths is None
                       else graph.entities[owner].path in diagnostic_paths)
        graph.add(owner,'CFG_STATUS','partial' if missing or diagnostics else 'structured',
                  level='statement', excluded='expression-evaluation,exceptions,suspension',
                  reasons=sorted(missing), analysis='structured-cfg/2', gaps=sorted(gaps),
                  language=graph.entities[owner].attrs.get('language'))
