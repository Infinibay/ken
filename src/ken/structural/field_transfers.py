"""Last direct parameter-to-field writes and simple field getters.

Linear syntax model: no hidden effects, runtime purity or whole-heap guarantees.
"""
from collections import defaultdict

from .model import FactIndex, IR


def field_transfers(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    operations = {o.id: o for o in graph.operations}
    by_owner = defaultdict(list)
    for op in graph.operations:
        by_owner[op.owner].append(op)
    owners = {f.object: f.subject for f in index.rows('HAS_METHOD')}
    fields = defaultdict(set)
    params = defaultdict(set)
    receiver_names = defaultdict(set)
    for f in index.rows('HAS_FIELD'):
        if not graph.entities[f.object].attrs.get('static'):
            fields[f.subject].add(f.object)
    for f in index.rows('HAS_PARAMETER'):
        if not f.attrs.get('receiver'):
            params[f.subject].add(f.object)
        else:
            receiver_names[f.subject].add(graph.entities[f.object].name)
    implicit: dict[str, dict[str, str]] = defaultdict(dict)
    parameter_owners = {p: owner for owner, values in params.items() for p in values}
    for f in index.rows('PARAMETER_INITIALIZES_FIELD'):
        owner = parameter_owners.get(f.subject)
        if owner is not None:
            implicit[owner][f.object] = f.subject
    initializer_owners = {f.object:f.subject for f in index.rows('HAS_INITIALIZER')
                          if f.attrs.get('basis') == 'cpp-constructor-syntax'}
    initialized_fields = {f.subject:f.object for f in index.rows('INITIALIZES_FIELD')}
    unsupported_initializers = {initializer_owners[f.subject] for f in index.rows('CONSTRUCTOR_INITIALIZER_STATUS')
                                if f.object == 'unsupported' and f.subject in initializer_owners}
    for f in index.rows('CONSTRUCTOR_INITIALIZER_INPUT'):
        owner = initializer_owners.get(f.subject)
        slot = initialized_fields.get(f.subject)
        if owner is not None and slot is not None and parameter_owners.get(f.object) == owner:
            implicit[owner][slot] = f.object
    targets = {f.subject: f.object for f in index.rows('ASSIGNMENT_TARGET')}
    values = {f.subject: f.object for f in index.rows('ASSIGNMENT_VALUE')}
    returns = {f.subject: f.object for f in index.rows('RETURN_OPERAND')}
    call_owners = {f.object: f.subject for f in index.rows('HAS_CALL')}
    escaped = {call_owners.get(f.subject) for relation in ['ARGUMENT', 'RECEIVER'] for f in index.rows(relation)
               if f.object.endswith('/THIS')}
    nested = {f.object for f in index.rows('OWNED_BY') if graph.entities[f.subject].kind == 'CALLABLE'}
    dynamic = {call_owners.get(f.subject) for f in index.rows('CALLEE_NAME')
               if f.object in {'eval', 'exec', 'locals', 'globals', '_getframe', 'currentframe'}}
    containers = {'expression_statement', 'lexical_declaration', 'variable_declaration',
                  'local_variable_declaration', 'local_declaration_statement', 'declaration'}
    for owner, cls in owners.items():
        entity = graph.entities[owner]
        ops = by_owner[owner]
        if entity.attrs.get('language') not in {'python', 'javascript', 'typescript', 'java', 'csharp', 'cpp'}:
            continue
        if not implicit[owner] and not any(o.id in targets or o.id in returns for o in ops):
            continue
        bodies = [o.id for o in ops if o.role == 'body' and o.parent in operations
                  and operations[o.parent].kind == 'FUNCTION']
        for op in ops:
            named_receiver = (op.native_kind in {'identifier', 'this', 'self', 'this_expression'}
                              and op.attrs.get('text') in receiver_names[owner] | {'this'})
            embedded_receiver = 'this' in op.attrs.get('tokens', []) and op.kind != 'MEMBER'
            if not named_receiver and not embedded_receiver:
                continue
            immediate = operations.get(op.parent or '')
            if (entity.attrs.get('language') == 'java' and entity.attrs.get('constructor')
                    and named_receiver and op.role == 'constructor' and immediate is not None
                    and immediate.native_kind == 'explicit_constructor_invocation'
                    and immediate.parent in bodies):
                # A leading this() initializer is not publication of the bare
                # receiver. Only the subsequent explicit field writes are
                # summarized; no delegated-constructor field values are assumed.
                siblings = [o for o in ops if o.parent == immediate.parent]
                arguments = [o for o in ops if o.parent == immediate.id and o.role == 'arguments']
                if (siblings and min(siblings, key=lambda o: o.start).id == immediate.id
                        and len(arguments) == 1 and arguments[0].attrs.get('text') == '()'):
                    continue
            if named_receiver and immediate is not None and immediate.kind == 'MEMBER':
                continue
            current = immediate
            for _ in range(32):
                if current is None:
                    break
                if current.id in bodies:
                    escaped.add(owner)  # Bare receiver use includes aliases/container publication.
                    break
                current = operations.get(current.parent or '')
        reason = ''
        if len(bodies) != 1 or owner in escaped or owner in nested or owner in dynamic:
            reason = 'body-or-escape'
        elif owner in unsupported_initializers:
            reason = 'unsupported-constructor-initializer'
        elif any(o.kind in {'LOOP', 'BRANCH', 'TRY', 'THROW', 'YIELD', 'AWAIT', 'RESOURCE_SCOPE', 'MATCH', 'UPDATE'}
                 or o.native_kind in {'global_statement', 'nonlocal_statement', 'delete_statement', 'named_expression'}
                 or any(t in {'ref', 'out', '++', '--', '+=', '-=', '*=', '/=', '%=', '??=', '&&=', '||='}
                        for t in o.attrs.get('tokens', [])) for o in ops):
            reason = 'control-or-indirect-write'
        writes = [o for o in ops if o.id in targets]
        exits = [o for o in ops if o.kind == 'RETURN']
        for op in [*writes, *exits]:
            current = operations.get(op.parent or '')
            while current is not None and current.native_kind in containers:
                current = operations.get(current.parent or '')
            if current is None or current.id not in bodies:
                reason = reason or 'nested-event'
        if any(o.kind == 'ASSIGN' and o.id not in targets for o in ops):
            reason = reason or 'unmodeled-write'
        graph.add(owner, 'FIELD_FLOW_STATUS', 'unsupported' if reason else 'supported',
                  analysis='linear-fields/1', reason=reason)
        if reason:
            continue
        mutated = {targets[o.id] for o in writes}
        for f in index.rows('HAS_CALL', owner):
            for receiver in index.rows('RECEIVER', f.object):
                if receiver.object in params[owner] and receiver.object not in mutated:
                    graph.add(f.object, 'CALL_RECEIVER_INPUT', receiver.object, *receiver.evidence[:1],
                              basis='linear-syntax', analysis='linear-fields/1')
        last = {}
        for op in sorted([*writes, *exits], key=lambda o: o.start):
            if op.kind == 'RETURN':
                field = returns.get(op.id)
                if field in fields[cls] and field not in mutated:
                    graph.add(owner, 'RETURNS_FIELD', field, f'{entity.path}:{op.line}',
                              basis='linear-syntax', return_operation=op.id)
                break
            last[targets[op.id]] = op
        final_inputs = dict(implicit[owner])
        for field, write in last.items():
            final_inputs[field] = values[write.id]
            value = values[write.id]
            if field in fields[cls]:
                graph.add(write.id, 'FINAL_FIELD_VALUE', value, f'{entity.path}:{write.line}',
                          basis='linear-syntax', analysis='linear-fields/1')
            if field in fields[cls] and value in params[owner] and value not in mutated:
                graph.add(write.id, 'FINAL_FIELD_INPUT', value, f'{entity.path}:{write.line}',
                          basis='linear-syntax', analysis='linear-fields/1')
        if entity.attrs.get('constructor'):
            for field, value in final_inputs.items():
                if field in fields[cls] and value in params[owner] and value not in mutated:
                    graph.add(field, 'CONSTRUCTOR_FIELD_INPUT', value, f'{entity.path}:{entity.line}',
                              basis='linear-syntax', analysis='linear-fields/1')
