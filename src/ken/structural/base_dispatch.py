"""Resolve language-accredited super/base invocations along one class chain."""
from collections import defaultdict


def resolve(graph):
    bases=defaultdict(set);methods=defaultdict(list);base_names=defaultdict(set)
    for fact in graph.facts:
        if fact.relation=='SUBTYPE_OF':
            base=graph.entities.get(fact.object)
            if base is not None and base.kind in ('CLASS','STRUCT'):bases[fact.subject].add(fact.object)
        elif fact.relation=='BASE_NAME':base_names[fact.subject].add(fact.object)
        elif fact.relation=='HAS_METHOD':methods[fact.subject].append(fact.object)
    selected={e.id for e in graph.entities.values() if e.kind=='CALL' and e.attrs.get('base_dispatch_owner')}
    if not selected:return
    graph.facts=[f for f in graph.facts if not(f.subject in selected and f.relation in ('TARGET','DECLARED_TARGET','MAY_TARGET'))]
    for call in graph.entities.values():
        owner=call.attrs.get('base_dispatch_owner')
        if call.kind!='CALL' or not owner:continue
        # Existing instance dispatch may have selected the overriding method;
        # base syntax never dispatches virtually back into that override.
        seen=set();target=None
        while owner not in seen and len(seen)<32:
            seen.add(owner)
            if len(bases[owner])!=1:break
            if call.attrs.get('language')=='python' and len(base_names[owner])!=1:break
            owner=next(iter(bases[owner]))
            candidates=[graph.entities[m] for m in methods[owner]
                        if graph.entities[m].name==call.attrs.get('name')]
            if candidates:
                if len(candidates)==1 and not candidates[0].attrs.get('static'):
                    target=candidates[0].id
                break
        call.attrs['resolution']='resolved' if target else 'unresolved'
        if target:
            graph.add(call.id,'TARGET',target,basis='lexical-base-dispatch')
