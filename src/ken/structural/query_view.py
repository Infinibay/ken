"""Normalize semantic IR facts into the relational query view, without mutation."""
from __future__ import annotations

from dataclasses import replace

from .model import IR, Entity, FactIndex


def query_graph(ir: IR) -> FactIndex:
    """Compatibility facade for callers that need in-memory posting lists."""
    return FactIndex(normalize_query_graph(ir))


def normalize_query_graph(ir: IR) -> IR:
    """A non-mutating view with argument occurrences and normalized query metadata.

    Kept separate from legacy facts so previously stored queries retain semantics.
    """
    if ir.view == "query":
        return ir
    graph=IR(ir.path,ir.language,dict(ir.entities),list(ir.operations),[],set(ir.capabilities),list(ir.diagnostics))
    graph.entities = {key: replace(e, name=e.attrs.get("name", e.name)) if e.kind == "CALL" else e for key,e in graph.entities.items()}
    graph.view = "query"
    graph.relations = set(ir.relations)
    methods={f.object for f in ir.facts if f.relation=='HAS_METHOD'}
    arities: dict[str, set[str]] = {}
    for fact in ir.facts:
        if fact.relation == 'HAS_PARAMETER' and not fact.attrs.get('receiver'):
            arities.setdefault(fact.subject, set()).add(fact.object)
    generators={f.subject for f in ir.facts if f.relation=='HAS_YIELD'}
    def family(value):
        return {'str':'string','string':'string','String':'string','int':'integer','bool':'boolean','boolean':'boolean'}.get(value,value)
    if not ir.diagnostics:
        for entity in ir.entities.values():
            if entity.kind == 'CALLABLE':
                if entity.attrs.get('language') == 'python':
                    graph.capabilities.add(f'complete:{entity.id}:HAS_PARAMETER')
                # Every call form of the eight analysed languages is classified, so
                # a callable's own calls are enumerated, not sampled. This is what
                # lets a query ask for an exact call cardinality or for the absence
                # of a call. ``tests/structural/test_call_cardinality_closure.py``
                # enumerates the call forms per language; if a grammar renames one,
                # that test fails before the claim becomes a lie. Rust macro
                # invocations are not calls and are deliberately not counted.
                graph.capabilities.add(f'complete:{entity.id}:HAS_CALL')
    call_ids = {e.id for e in ir.entities.values() if e.kind == 'CALL'}
    results = {call: call + '/result' for call in call_ids}
    stored: dict[str, list[str]] = {}
    supported_returns = {f.subject for f in ir.facts
                         if f.relation == 'RETURN_FLOW_STATUS' and f.object == 'supported'}
    return_operations = {o.id: o for o in ir.operations if o.kind == 'RETURN'}
    for fact in ir.facts:
        if fact.relation == 'ASSIGNED_FROM':
            stored.setdefault(fact.subject, []).append(fact.object)
    # Per-argument occurrence facts retain exact source value IDs. Callee names
    # cannot identify results: two calls to the same function may return anything.
    argument_origins = {
        (f.subject, f.object, f.attrs.get('position', 0)): f
        for f in ir.facts if f.relation == 'ARGUMENT_ORIGIN'
    }

    def as_value(source: str, occurrence: str, evidence: list[str], consumer_call: str | None = None,
                 position: int = 0) -> str:
        if source in results:
            return results[source]
        entity = ir.entities.get(source)
        if entity is None or entity.kind not in {'STORAGE', 'PARAMETER'}:
            return source
        value_id = occurrence + '/loaded-value'
        graph.entities[value_id] = Entity(value_id, 'VALUE', entity.name, entity.path, entity.line, entity.end_line,
                                          {'origin': 'load', 'storage': source})
        graph.add(value_id, 'ENTITY', 'VALUE', *evidence[:1], type=entity.attrs.get('type', 'unknown'))
        graph.add(value_id, 'LOADED_FROM', source, *evidence[:1])
        origin = argument_origins.get((consumer_call, source, position)) if consumer_call is not None else None
        live = set(origin.attrs.get('origins', ())) if origin is not None else set()
        for incoming in sorted(set(stored.get(source, ())) | live):
            if incoming not in results:
                continue
            is_must = (origin is not None and origin.attrs.get('modality') == 'must'
                       and incoming in live)
            graph.add(results[incoming], 'VALUE_FLOW', value_id, *evidence[:1],
                      modality='must' if is_must else 'may')
        return value_id

    for call, value_id in results.items():
        entity = ir.entities[call]
        graph.entities[value_id] = Entity(value_id, 'VALUE', '', entity.path, entity.line, entity.end_line, {'origin': call})
        graph.add(value_id, 'ENTITY', 'VALUE')
        graph.add(call, 'RESULT', value_id)
    for f in ir.facts:
        if f.relation=='ARGUMENT':
            aid=f'{f.subject}/argument/{f.attrs.get("position",0)}'
            graph.add(f.subject,'ARGUMENT',aid,*f.evidence[:1])
            graph.add(aid,'VALUE',as_value(f.object,aid,f.evidence,consumer_call=f.subject,position=f.attrs.get("position",0)),*f.evidence[:1])
            source_entity=ir.entities.get(f.object)
            source_attrs=source_entity.attrs if source_entity else {}
            argument_attrs={**f.attrs, 'type':source_attrs.get('type','unknown'), 'type_family':family(source_attrs.get('type','unknown')), 'type_state':'known' if source_attrs.get('native_type') or source_attrs.get('type','unknown')!='unknown' else 'unknown'}
            graph.add(aid,'ENTITY','ARGUMENT',*f.evidence[:1],**argument_attrs)
            continue
        if f.relation=='ENTITY':
            attrs=dict(f.attrs)
            attrs.update(type_family=family(attrs.get('type','unknown')),
                         type_state='known' if attrs.get('native_type') or attrs.get('type','unknown')!='unknown' else 'unknown',
                         return_family=family(attrs.get('return_type','unknown')),
                         return_type_state='known' if attrs.get('native_return_type') or attrs.get('return_type','unknown')!='unknown' else 'unknown',
                         position=attrs.get('pos',attrs.get('position')), kind=attrs.get('parameter_kind',f.object.lower()),
                         method=f.subject in methods, generator=attrs.get('generator',False) or f.subject in generators)
            attrs['async'] = attrs.get('async_',False)
            attrs['arity'] = len(arities.get(f.subject, set())) if not ir.diagnostics else None
            selected_entity = ir.entities.get(f.subject)
            if selected_entity:
                attrs["path"] = selected_entity.path
                if selected_entity.kind == "CALL": attrs["name"] = selected_entity.attrs.get("name", selected_entity.name)
            graph.facts.append(replace(f,attrs=attrs))
        elif f.relation=='OPERATION':
            kind=str(f.attrs.get('kind',f.object)).lower()
            if kind=='yield' and f.attrs.get('delegated'): kind='yield_delegate'
            if kind=='yield' and 'break' in f.attrs.get('tokens',[]): kind='generator_stop'
            graph.facts.append(replace(f,attrs={**f.attrs,'kind':kind}))
        else: graph.facts.append(f)
        if f.relation == 'ALLOCATES_TYPE':
            graph.add(results.get(f.subject, f.subject), 'INSTANCE_OF', f.object, *f.evidence[:1])
        elif f.relation in {'RETURNS', 'ASSIGNED_FROM'}:
            if f.relation != 'RETURNS' or f.subject not in supported_returns:
                value = as_value(f.object, f.subject + '/' + f.relation + '/' + f.object, f.evidence)
                graph.add(f.subject, 'RETURNS_VALUE' if f.relation == 'RETURNS' else 'STORES_VALUE',
                          value, *f.evidence[:1], **({'basis': 'syntax'} if f.relation == 'RETURNS' else {}))
        elif f.relation == 'FLOWS_TO' and f.subject in results and f.object in results:
            graph.add(results[f.subject], 'VALUE_FLOW', results[f.object], *f.evidence[:1], modality='may')
    # A supported return captures its operand's current origin, rather than all
    # assignments to that binding. Keep the source RETURNS facts unchanged.
    # ``possible_call`` is the call graph closed under overriding: a call site names
    # the declared slot, and the pattern usually binds the implementation. Publishing
    # the expansion once keeps the query a single fact join instead of a disjunction.
    overrides: dict[str, set[str]] = {}
    for fact in ir.facts:
        if fact.relation == 'OVERRIDES':
            overrides.setdefault(fact.object, set()).add(fact.subject)
    for fact in ir.facts:
        if fact.relation != 'CALLS':
            continue
        # Keep the source reachability: dead code stays ``unreachable``.
        graph.add(fact.subject, 'POSSIBLE_CALL', fact.object, *fact.evidence[:1], **fact.attrs)
        for implementation in sorted(overrides.get(fact.object, ())):
            graph.add(fact.subject, 'POSSIBLE_CALL', implementation, *fact.evidence[:1], **fact.attrs)

    # ``DELEGATES_TO`` records the *name* of the operation a callable invokes on a
    # receiver place, but a name is a string, not an entity, so no fact join can
    # correlate it with the slot a method overrides. Publish that join once: a
    # callable forwards a slot when it delegates a call spelled like the slot it
    # overrides. Reachability rides along, so a forwarding call in dead code stays
    # unusable.
    names = {entity.id: entity.attrs.get('name', entity.name) for entity in ir.entities.values()}
    overridden: dict[str, set[str]] = {}
    for fact in ir.facts:
        if fact.relation == 'OVERRIDES':
            overridden.setdefault(fact.subject, set()).add(fact.object)
    for fact in ir.facts:
        if fact.relation != 'DELEGATES_TO' or not fact.attrs.get('name'):
            continue
        spelled = fact.attrs['name']
        for slot in sorted(overridden.get(fact.subject, ())):
            if names.get(slot) == spelled:
                graph.add(fact.subject, 'FORWARDS_SLOT', slot, *fact.evidence[:1], **fact.attrs)

    for fact in ir.facts:
        if fact.relation != 'RETURN_ORIGIN':
            continue
        operation = return_operations.get(fact.subject)
        if operation is None or operation.owner not in supported_returns:
            continue
        value = as_value(fact.object, fact.subject + '/return-origin/' + fact.object, fact.evidence)
        graph.add(operation.owner, 'RETURNS_VALUE', value, *fact.evidence[:1],
                  **{**fact.attrs, 'basis': 'flow', 'return_operation': operation.id})
    return graph
