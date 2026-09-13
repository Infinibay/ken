"""Bounded collection-copy models and occurrence-specific iteration provenance.

These are structural API models, not execution or runtime identity proofs.
Aliases are followed only through unique, lexically dominating local writes.
"""
import re
from collections import defaultdict, deque

from .model import FactIndex, IR, Operation


def collection_snapshots(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    entities = graph.entities
    operations = {op.id: op for op in graph.operations}
    syntax = {f.subject: f.object for f in index.rows('SYNTAX_NODE')}
    args = defaultdict(list)
    for fact in index.rows('ARGUMENT'):
        args[fact.subject].append(fact)
    receivers = {f.subject: f.object for f in index.rows('RECEIVER')}
    callee_values = {f.subject: f.object for f in index.rows('CALLEE_VALUE')}
    writes = defaultdict(list)
    for fact in index.rows('ASSIGNMENT_TARGET'):
        writes[fact.object].append(fact.subject)
    rhs = {f.subject: f.object for f in index.rows('ASSIGNMENT_VALUE')}
    declared = {(f.subject, f.object) for f in index.rows('DECLARES')}
    written = {f.object for f in index.rows('WRITES')}
    unsafe_owners = {op.owner for op in graph.operations if op.kind == 'UPDATE'
                     or any(token in {'ref', 'out'} for token in op.attrs.get('tokens', []))
                     or op.native_kind in {'delete_statement', 'global_statement', 'nonlocal_statement',
                                           'named_expression', 'augmented_assignment', 'augmented_assignment_expression'}}
    unsafe_owners.update(str(entities[f.subject].attrs.get('owner', '')) for f in index.rows('CALLEE_NAME')
                         if f.object in {'eval', 'exec', 'locals', 'globals'})
    # Unknown calls may mutate an escaped collection. Propagate that exclusion
    # through aliases, including aliases that are not on the loop's origin path.
    unsafe_values = set(receivers.values()) | {f.object for f in index.rows('ARGUMENT')}
    unsafe_values.update(f.object for f in index.rows('WRITES_ELEMENT'))
    aliases = defaultdict(set)
    for target, definitions in writes.items():
        for definition in definitions:
            value = rhs.get(definition, '')
            if value in entities and entities[value].kind in {'STORAGE', 'PARAMETER'}:
                aliases[target].add(value)
                aliases[value].add(target)
    pending = deque(unsafe_values)
    while pending:
        value = pending.popleft()
        for alias in aliases[value] - unsafe_values:
            unsafe_values.add(alias)
            pending.append(alias)
    shadowed = set()
    for entity in entities.values():
        if entity.name in {'Array', 'list', 'tuple'} and (
                entity.kind in {'CLASS', 'INTERFACE', 'PARAMETER', 'CALLABLE'}
                or entity.attrs.get('declared')):
            shadowed.add((entity.path, entity.name))
    for fact in index.rows('IMPORT_SYNTAX'):
        for name in ('Array', 'list', 'tuple'):
            if re.search(r'\b' + name + r'\b', fact.object) or '*' in fact.object:
                shadowed.add((fact.subject.removesuffix('::module'), name))
    # An explicit local replacement of Array.from invalidates its API model.
    for fact in index.rows('MEMBER_OF'):
        member, base = entities.get(fact.subject), entities.get(fact.object)
        if fact.subject in writes and member and base and base.name == 'Array':
            shadowed.add((base.path, 'Array'))

    parameters = {(f.subject, f.object) for f in index.rows('HAS_PARAMETER') if not f.attrs.get('receiver')}
    for fact in index.rows('INSERTED_VALUE'):
        owner = entities[fact.subject].attrs.get('owner', '')
        if (owner, fact.object) in parameters and fact.object not in written and owner not in unsafe_owners:
            graph.add(fact.subject, 'INSERTED_INPUT', fact.object, *fact.evidence[:1], basis='syntax-unwritten-binding')
    calls = {e.id for e in entities.values() if e.kind == 'CALL'}
    snapshots = set()
    for call_entity in (e for e in entities.values() if e.kind == 'CALL'):
        arguments = args[call_entity.id]
        if len(arguments) != 1 or arguments[0].attrs.get('kind') != 'positional':
            continue
        language = call_entity.attrs.get('language')
        name = str(call_entity.attrs.get('name', ''))
        model = ''
        if language == 'python' and name in {'list', 'tuple'} and call_entity.id not in receivers:
            if call_entity.id not in callee_values and (call_entity.path, name) not in shadowed:
                model = 'python.' + str(name)
        elif language in {'javascript', 'typescript'} and name == 'from':
            receiver = entities.get(receivers.get(call_entity.id, ''))
            if (receiver and receiver.name == 'Array' and receiver.kind == 'STORAGE'
                    and receiver.attrs.get('native_kind') == 'identifier'
                    and (call_entity.path, 'Array') not in shadowed):
                model = 'javascript.Array.from'
        if model:
            graph.add(call_entity.id, 'COLLECTION_SNAPSHOT_OF', arguments[0].object,
                      f'{call_entity.path}:{call_entity.line}', model=model, basis='api-model')
            snapshots.add(call_entity.id)

    wrappers = {'expression_statement', 'lexical_declaration', 'variable_declaration',
                'local_variable_declaration', 'local_declaration_statement'}
    blocks = {'block', 'statement_block'}

    def dominates(write: Operation, use: Operation) -> bool:
        """A simple statement in a containing sequence, before the use's subtree."""
        current = write
        for _ in range(64):
            parent = operations.get(current.parent or '')
            if parent is None or parent.owner != write.owner:
                return False
            if parent.native_kind in blocks:
                sequence = parent.id
                break
            if parent.native_kind not in wrappers:
                return False
            current = parent
        else:
            return False
        current = use
        for _ in range(64):
            if current.parent == sequence:
                return write.end <= current.start
            parent = operations.get(current.parent or '')
            if parent is None or parent.owner != write.owner:
                return False
            current = parent
        return False

    def origin(value: str, use: Operation) -> str | None:
        if use.owner in unsafe_owners:
            return None
        seen = set()
        for _ in range(32):
            if value in calls:
                return value
            if (value in seen or value in unsafe_values or value in binding_loops
                    or (use.owner, value) not in declared):
                return None
            seen.add(value)
            definitions = writes[value]
            if len(definitions) != 1:
                return None
            write = operations.get(definitions[0])
            if (write is None or write.owner != use.owner or not dominates(write, use)
                    or write.id not in rhs
                    or any(t.endswith('=') and t != '=' for t in write.attrs.get('tokens', []))):
                return None
            value, use = rhs[write.id], write
        return None

    bindings = defaultdict(list)
    binding_loops = defaultdict(set)
    for fact in index.rows('ITERATION_BINDING'):
        binding_loops[fact.object].add(fact.subject)
        if fact.attrs.get('role') == 'value':
            bindings[fact.subject].append(fact.object)
    loops = {f.subject: f.object for f in index.rows('ENCLOSING_LOOP')}
    calls_in_loop = defaultdict(list)
    for call, node in syntax.items():
        if node in loops:
            calls_in_loop[loops[node]].append(call)
    for fact in index.rows('ITERATION_SOURCE'):
        loop = operations.get(fact.subject)
        if loop is None:
            continue
        producer = origin(fact.object, loop)
        if producer:
            graph.add(loop.id, 'ITERATION_ORIGIN', producer, *fact.evidence[:1], basis='unique-local-write')
            if producer in snapshots:
                graph.add(loop.id, 'ITERATION_SNAPSHOT', producer, *fact.evidence[:1],
                          basis='unique-local-write', model='collection-snapshot/1')
        for binding in bindings[loop.id]:
            if binding in written or loop.owner in unsafe_owners or len(binding_loops[binding]) != 1:
                continue
            for call in calls_in_loop[loop.id]:
                if entities[call].attrs.get('owner') != loop.owner:
                    continue
                for argument in args[call]:
                    if argument.object == binding and argument.attrs.get('kind') == 'positional':
                        entity = entities[call]
                        graph.add(loop.id, 'ITERATION_PASSES_VALUE', call,
                                  f'{entity.path}:{entity.line}', position=argument.attrs['position'], basis='syntax-unwritten-binding')
                invoked = receivers.get(call, callee_values.get(call, ''))
                if invoked == binding:
                    entity = entities[call]
                    graph.add(loop.id, 'ITERATION_INVOKES_VALUE', call,
                              f'{entity.path}:{entity.line}', basis='syntax')
