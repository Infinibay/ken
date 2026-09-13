"""Statement-level structured CFG, with explicit partial coverage.

Expression evaluation, short circuit, exceptions and suspension are not expanded
here. Edges describe normal structured control, not feasible runtime paths.
"""
from collections import defaultdict

from .model import IR, Operation


def structured_control(graph: IR) -> None:
    operations = {op.id: op for op in graph.operations}
    children: dict[str, list[Operation]] = defaultdict(list)
    by_owner: dict[str, list[Operation]] = defaultdict(list)
    for op in graph.operations:
        by_owner[op.owner].append(op)
        parent = operations.get(op.parent or '')
        if parent is not None and parent.owner == op.owner:
            children[parent.id].append(op)
    for siblings in children.values():
        siblings.sort(key=lambda op: op.start)
    blocks = {'block','statement_block','compound_statement','else_clause','statement_list'}
    loops = {'while_statement','while_expression','for_statement','for_in_statement',
             'enhanced_for_statement','for_each_statement','foreach_statement','for_expression',
             'loop_expression','do_statement','for_range_loop'}
    unsupported = {'try_statement','try_with_resources_statement','with_statement','using_statement',
                   'switch_statement','switch_expression','match_expression','match_statement',
                   'goto_statement','labeled_statement','lock_statement','synchronized_statement'}
    for body in graph.operations:
        parent = operations.get(body.parent or '')
        if body.role != 'body' or parent is None or parent.kind != 'FUNCTION' or body.owner != parent.owner:
            continue
        owner = body.owner
        exit_id = owner + '::cfg-exit'
        edges: list[tuple[str,str,str]] = []
        facts: list[tuple[str,str,str]] = []
        missing = set()

        def edge(a: str, b: str, kind: str = 'next') -> None:
            edges.append((a,b,kind))

        def build(op: Operation, after: str, break_to: str | None = None,
                  continue_to: str | None = None, depth: int = 0, false_after: str | None = None) -> str:
            if depth > 64:
                missing.add('nesting-limit')
                return after
            nested = children[op.id]
            fields = {c.role:c for c in nested if c.role}
            if op.native_kind == 'expression_statement' and len(nested) == 1 and nested[0].native_kind in loops | {'if_expression','return_expression','break_expression','continue_expression'}:
                return build(nested[0],after,break_to,continue_to,depth+1)
            if op.native_kind in blocks:
                entry = after
                for child in reversed(nested):
                    if 'comment' not in child.native_kind:
                        entry = build(child,entry,break_to,continue_to,depth+1)
                return entry
            if op.native_kind in {'if_statement','if_expression','elif_clause'}:
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
                foreach = (op.native_kind in {'for_in_statement','enhanced_for_statement','for_each_statement','foreach_statement','for_expression','for_range_loop'}
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
            if op.native_kind in {'break_statement','continue_statement','break_expression','continue_expression'}:
                is_break = op.native_kind.startswith('break')
                target = break_to if is_break else continue_to
                if target is None or any('comment' not in c.native_kind for c in nested):
                    missing.add('label-or-control-target')
                else:
                    edge(op.id,target,'break' if is_break else 'continue')
                return op.id
            if op.native_kind in {'return_statement','return_expression'}:
                edge(op.id,exit_id,'return')
                return op.id
            if op.native_kind in unsupported or op.kind in {'TRY','THROW','YIELD','AWAIT','RESOURCE_SCOPE','MATCH'}:
                missing.add(op.native_kind)
            edge(op.id,after)
            return op.id

        entry = build(body,exit_id)
        # Report expression-level effects even when wrapped in an atomic statement.
        for op in by_owner[owner]:
            if op.kind in {'YIELD','AWAIT','THROW'}:
                missing.add(op.native_kind)
        graph.add(owner,'CFG_ENTRY',entry,basis='structured-syntax')
        graph.add(owner,'CFG_EXIT',exit_id,basis='structured-syntax')
        for a,b,kind in sorted(set(edges)):
            graph.add(a,'CFG_NEXT',b,kind=kind,basis='structured-syntax')
        for a,r,b in facts:
            graph.add(a,r,b,basis='syntax')
        graph.add(owner,'CFG_STATUS','partial' if missing or graph.diagnostics else 'structured',
                  level='statement', excluded='expression-evaluation,exceptions,suspension',
                  reasons=sorted(missing), analysis='structured-cfg/1')
