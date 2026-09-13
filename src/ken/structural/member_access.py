"""Nominal instance slots and bounded syntactic access provenance.

These facts describe an instance-relative location and an input access path,
not object identity, getter purity, or runtime dispatch/execution guarantees.
"""
from collections import defaultdict

from .model import FactIndex, IR, Operation


def member_access(graph: IR) -> None:
    if graph.diagnostics:
        return
    index = FactIndex(graph)
    entities = graph.entities
    bases = defaultdict(set)
    spellings = defaultdict(set)
    fields: dict[str, dict[str, str]] = defaultdict(dict)
    methods: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for fact in index.rows('SUBTYPE_OF'):
        bases[fact.subject].add(fact.object)
    for fact in index.rows('BASE_NAME'):
        spellings[fact.subject].add(fact.object)
    for fact in index.rows('HAS_FIELD'):
        fields[fact.subject][entities[fact.object].name] = fact.object
    for fact in index.rows('HAS_METHOD'):
        methods[fact.subject][entities[fact.object].name].append(fact.object)

    def lineage(unit: str) -> list[str]:
        result: list[str] = []
        while unit not in result and len(result) < 32:
            result.append(unit)
            if len(bases[unit]) > 1 or len(spellings[unit]) != len(bases[unit]):
                return []  # Unresolved or multiple inheritance has no guessed MRO.
            if not bases[unit]:
                return result
            unit = next(iter(bases[unit]))
        return []

    for unit in (e for e in entities.values() if e.kind == 'CLASS'
                 and e.attrs.get('language') in {'python', 'javascript', 'typescript'}):
        chain = lineage(unit.id)
        if not chain:
            continue
        visible: dict[str, list[str]] = {}
        for cls in reversed(chain):
            visible.update(methods[cls])
            for name, field in fields[cls].items():
                if entities[field].attrs.get('declared'):
                    visible.pop(name, None)
        for definitions in visible.values():
            if len(definitions) == 1:
                method = definitions[0]
                if any(str(d).removeprefix('@').endswith(('property', '.setter', '.deleter'))
                       for d in entities[method].attrs.get('decorators', [])):
                    continue
                graph.add(unit.id, 'EFFECTIVE_METHOD', method,
                          f'{entities[method].path}:{entities[method].line}', basis='single-inheritance')
        for name, field in fields[unit.id].items():
            if name.startswith('#') or name.startswith('__') and not name.endswith('__'):
                continue
            candidates = [fields[cls][name] for cls in reversed(chain) if name in fields[cls]]
            if (any(entities[candidate].attrs.get('static') for candidate in candidates)
                    or any(name in methods[cls] for cls in chain)):
                continue
            graph.add(field, 'INSTANCE_SLOT', candidates[0],
                      f'{unit.path}:{entities[field].line}', basis='single-inheritance', relative_to=unit.id)

    operations = {op.id: op for op in graph.operations}
    locations = {(entities[op.owner].path, op.start, op.end, op.native_kind): op
                 for op in graph.operations}
    members = defaultdict(set)
    writes = defaultdict(set)
    rhs = {f.subject: f.object for f in index.rows('ASSIGNMENT_VALUE')}
    locals_ = {(f.subject, f.object) for f in index.rows('DECLARES')}
    params = {(f.subject, f.object) for f in index.rows('HAS_PARAMETER') if not f.attrs.get('receiver')}
    loop_bindings = {f.object for f in index.rows('ITERATION_BINDING')}
    for fact in index.rows('MEMBER_OF'):
        members[fact.subject].add(fact.object)
    for fact in index.rows('ASSIGNMENT_TARGET'):
        writes[fact.object].add(fact.subject)
    unsafe = {op.owner for op in graph.operations if op.kind == 'UPDATE'
              or op.native_kind in {'delete_statement', 'global_statement', 'nonlocal_statement',
                                    'named_expression', 'augmented_assignment', 'augmented_assignment_expression'}}
    unsafe.update(str(entities[f.subject].attrs.get('owner', '')) for f in index.rows('CALLEE_NAME')
                  if f.object in {'eval', 'exec', 'locals', 'globals'})

    def precedes(write: Operation, use: Operation) -> bool:
        current = write
        for _ in range(64):
            parent = operations.get(current.parent or '')
            if parent is None or parent.owner != write.owner:
                return False
            if parent.native_kind in {'block', 'statement_block'}:
                block = parent.id
                break
            if parent.native_kind not in {'expression_statement', 'lexical_declaration', 'variable_declaration'}:
                return False
            current = parent
        else:
            return False
        current = use
        for _ in range(64):
            if current.parent == block:
                return write.end <= current.start
            parent = operations.get(current.parent or '')
            if parent is None or parent.owner != write.owner:
                return False
            current = parent
        return False

    for access, parents in list(members.items()):
        entity = entities[access]
        use = locations.get((entity.path, entity.attrs.get('start_byte', -1),
                             entity.attrs.get('end_byte', -1), entity.attrs.get('native_kind', '')))
        if use is None or use.owner in unsafe:
            continue
        value = access
        seen = set()
        steps: list[str] = []
        definitions = []
        for _ in range(32):
            if value in seen or value in loop_bindings:
                break
            seen.add(value)
            if (use.owner, value) in params:
                if not writes[value]:
                    graph.add(access, 'ACCESS_INPUT', value, f'{entity.path}:{entity.line}',
                              basis='syntax-local-alias', members=list(reversed(steps)), assignments=definitions)
                break
            if len(members[value]) == 1:
                steps.append(entities[value].name)
                value = next(iter(members[value]))
                continue
            if (use.owner, value) not in locals_ or len(writes[value]) != 1:
                break
            write = operations.get(next(iter(writes[value])))
            if (write is None or write.id not in rhs or not precedes(write, use)
                    or any(t.endswith('=') and t != '=' for t in write.attrs.get('tokens', []))):
                break
            definitions.append(write.id)
            value, use = rhs[write.id], write
