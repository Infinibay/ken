"""Last written parameter input to bindings and members in linear callable bodies."""
from collections import defaultdict
from .model import FactIndex, IR


def member_transfers(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    operations = {o.id: o for o in graph.operations}
    by_owner = defaultdict(list)
    for op in graph.operations:
        by_owner[op.owner].append(op)
    targets = {f.subject: f.object for f in index.rows('ASSIGNMENT_TARGET')}
    values = {f.subject: f.object for f in index.rows('ASSIGNMENT_VALUE')}
    members = {f.subject for f in index.rows('MEMBER_OF')}
    # Direct instance fields can be canonical storage slots without a MEMBER_OF
    # edge (including implicit `this` accesses). Keep their assignment identity.
    members.update(f.object for f in index.rows('HAS_FIELD')
                   if not graph.entities[f.object].attrs.get('static'))
    bindings = members | {e.id for e in graph.entities.values() if e.kind in {'STORAGE', 'PARAMETER'}}
    params = defaultdict(set)
    for f in index.rows('HAS_PARAMETER'):
        if not f.attrs.get('receiver'):
            params[f.subject].add(f.object)
    nested = {f.object for f in index.rows('OWNED_BY') if graph.entities[f.subject].kind == 'CALLABLE'}
    dynamic = {graph.entities[f.subject].attrs.get('owner') for f in index.rows('CALLEE_NAME')
               if f.object in {'eval', 'exec', 'locals', 'globals', '_getframe', 'currentframe'}}
    containers = {'expression_statement', 'lexical_declaration', 'variable_declaration',
                  'local_variable_declaration', 'local_declaration_statement', 'declaration',
                  'statement_list'}
    for owner, ops in by_owner.items():
        entity = graph.entities[owner]
        if entity.kind != 'CALLABLE' or entity.attrs.get('language') not in {
                'python', 'javascript', 'typescript', 'java', 'csharp', 'rust', 'cpp', 'go', 'ruby'}:
            continue
        member_writes = any(targets.get(op.id) in members for op in ops)
        if not any(op.id in targets for op in ops):
            continue
        bodies = [o.id for o in ops if o.role == 'body' and o.parent in operations
                  and operations[o.parent].kind == 'FUNCTION']
        reason = ''
        if len(bodies) != 1 or owner in nested or owner in dynamic:
            reason = 'body-or-dynamic-scope'
        if any(o.kind in {'LOOP', 'BRANCH', 'TRY', 'THROW', 'YIELD', 'AWAIT', 'RESOURCE_SCOPE', 'MATCH', 'UPDATE'}
               or o.native_kind in {'global_statement', 'nonlocal_statement', 'delete_statement', 'named_expression'}
               or any(t in {'ref', 'out', '++', '--', '+=', '-=', '*=', '/=', '%=', '??=', '&&=', '||='}
                      for t in o.attrs.get('tokens', [])) for o in ops):
            reason = reason or 'control-or-indirect-write'
        writes = [o for o in ops if o.id in targets]
        exits = [o for o in ops if o.kind == 'RETURN']
        for op in [*writes, *exits]:
            current = operations.get(op.parent or '')
            while current is not None and current.native_kind in containers:
                current = operations.get(current.parent or '')
            if current is None or current.id not in bodies:
                reason = reason or 'nested-event'
        if any(o.kind == 'ASSIGN' and (o.id not in targets or '=' not in o.attrs.get('tokens', [])
               or (targets[o.id] not in members and (graph.entities.get(targets[o.id]) is None
                   or graph.entities[targets[o.id]].kind not in {'STORAGE', 'PARAMETER'}))) for o in ops):
            reason = reason or 'unmodeled-write'
        graph.add(owner, 'BINDING_FLOW_STATUS', 'unsupported' if reason else 'supported',
                  analysis='linear-bindings/1', reason=reason)
        if member_writes:
            graph.add(owner, 'MEMBER_FLOW_STATUS', 'unsupported' if reason else 'supported',
                      analysis='linear-members/1', reason=reason)
        if reason:
            continue
        mutated = {targets[o.id] for o in writes}
        last = {}
        for op in sorted([*writes, *exits], key=lambda o: o.start):
            if op.kind == 'RETURN':
                break
            last[targets[op.id]] = op
        for target, write in last.items():
            value = values.get(write.id)
            if target in bindings and value in params[owner] and value not in mutated:
                graph.add(write.id, 'FINAL_BINDING_INPUT', value, f'{entity.path}:{write.line}',
                          basis='linear-syntax', analysis='linear-bindings/1')
            if target in members and value in params[owner] and value not in mutated:
                graph.add(write.id, 'FINAL_MEMBER_INPUT', value, f'{entity.path}:{write.line}',
                          basis='linear-syntax', analysis='linear-members/1')
