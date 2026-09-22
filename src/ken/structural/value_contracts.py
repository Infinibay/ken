"""Small explicit value contracts over supported source summaries."""
from collections import defaultdict

from .model import IR

RELATIONS = frozenset({'RETURN_FLOW_STATUS', 'RETURN_ORIGIN', 'TARGET', 'RECEIVER',
                       'DECORATED_BY', 'ASSIGNMENT_TARGET', 'CALLEE_VALUE', 'CALLEE_NAME',
                       'STORAGE_WRITE_COUNT', 'ASSIGNMENT_VALUE', 'DECLARES', 'OWNED_BY',
                       'HAS_PARAMETER', 'BASE_VALUE'})

def value_contracts(graph: IR) -> None:
    rows = defaultdict(list)
    for fact in graph.facts:
        if fact.relation in RELATIONS:
            rows[fact.relation].append(fact)
    operations = {op.id: op for op in graph.operations}
    return_owners = {op.id: op.owner for op in graph.operations if op.kind == 'RETURN'}
    supported = {f.subject for f in rows['RETURN_FLOW_STATUS'] if f.object == 'supported'}
    origins = defaultdict(set)
    for f in rows['RETURN_ORIGIN']:
        if f.subject in return_owners:
            origins[return_owners[f.subject]].add(f.object)
    targets = defaultdict(set)
    for f in rows['TARGET']:
        targets[f.subject].add(f.object)
    receivers = {f.subject for f in rows['RECEIVER']}
    decorated = {f.subject for f in rows['DECORATED_BY']}
    rebound = {f.object for f in rows['ASSIGNMENT_TARGET']}
    unsafe_targets = decorated | rebound
    dynamic_paths = {graph.entities[f.subject].path for f in rows['CALLEE_NAME']
                     if f.object in {'eval', 'exec', 'globals', 'locals', '_getframe', 'currentframe'}}
    dynamic_paths.update(graph.entities[op.owner].path for op in graph.operations
                         if op.native_kind == 'with_statement' and graph.entities[op.owner].attrs.get('language') in {'javascript', 'typescript'})
    callee_values = {f.subject: f.object for f in rows['CALLEE_VALUE']}

    def scalar(value):
        entity = graph.entities.get(value)
        return value == 'NULL' or (entity is not None and entity.kind == 'VALUE'
                                  and entity.attrs.get('type') in {'int', 'float', 'number', 'str', 'bool', 'char'})

    for entity in list(graph.entities.values()):
        if entity.kind == 'CALL':
            kind = 'unknown'
            if not graph.diagnostics and len(targets[entity.id]) == 1:
                target = next(iter(targets[entity.id]))
                if (target in supported and origins[target] and all(scalar(v) for v in origins[target])
                        and entity.id not in receivers and target not in unsafe_targets
                        and entity.path not in dynamic_paths and graph.entities[target].path not in dynamic_paths
                        and callee_values.get(entity.id) == target):
                    kind = 'scalar'
            graph.add(entity.id, 'CALL_RESULT_KIND', kind, basis='supported-local-return-origins/1')

    # A base alias must be a unique earlier, top-level local assignment. This
    # deliberately excludes conditional/uninitialized aliases and rebinding.
    counts = {f.subject: f.object for f in rows['STORAGE_WRITE_COUNT']}
    writes = defaultdict(list)
    values = {f.subject: f.object for f in rows['ASSIGNMENT_VALUE']}
    for f in rows['ASSIGNMENT_TARGET']:
        if f.subject in operations:
            writes[f.object].append(operations[f.subject])
    owners = {f.object: f.subject for f in rows['DECLARES']}
    owners.update({f.subject: f.object for f in rows['OWNED_BY']})
    params = {f.object: f.subject for f in rows['HAS_PARAMETER'] if not f.attrs.get('receiver')}
    wrappers = {'expression_statement', 'lexical_declaration', 'variable_declaration', 'declaration'}
    for f in rows['BASE_VALUE']:
        derived = graph.entities[f.subject]
        owner = owners.get(derived.id)
        current = f.object
        before = derived.attrs.get('start_byte', -1)
        seen: set[str] = set()
        while current not in seen and len(seen) < 32:
            seen.add(current)
            if params.get(current) == owner and counts.get(current) == '0':
                graph.add(derived.id, 'BASE_INPUT', current, *f.evidence[:1], basis='unique-preceding-base-alias/1')
                break
            if counts.get(current) != '1' or len(writes[current]) != 1:
                break
            write = writes[current][0]
            if write.owner != owner or write.start >= before or write.attrs.get('execution') != 'possible':
                break
            parent = operations.get(write.parent or '')
            while parent is not None and parent.native_kind in wrappers:
                parent = operations.get(parent.parent or '')
            if parent is None or parent.role != 'body' or parent.parent not in operations or operations[parent.parent].kind != 'FUNCTION':
                break
            before = write.start
            current = values.get(write.id, '')
