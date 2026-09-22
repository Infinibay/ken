"""Accredit direct Java single-abstract-method declarations, conservatively."""
from collections import defaultdict


def annotate(graph):
    methods=defaultdict(list)
    bases=set()
    declarations={o.owner:o for o in graph.operations if o.kind=='FUNCTION'}
    for fact in graph.facts:
        if fact.relation=='HAS_METHOD':methods[fact.subject].append(fact.object)
        elif fact.relation in ('SUBTYPE_OF','BASE_NAME'):bases.add(fact.subject)
    for entity in graph.entities.values():
        if entity.kind!='INTERFACE' or entity.attrs.get('language')!='java' or entity.id in bases:
            continue
        candidates=[]
        for identity in methods[entity.id]:
            method=graph.entities[identity]
            declaration=declarations.get(identity)
            if method.attrs.get('static') or method.attrs.get('visibility')=='private':continue
            # Public Object contracts do not establish a Java functional slot.
            # Excluding all overloads of these names is conservative.
            if method.name in {'equals','hashCode','toString'}:continue
            if declaration and ';' in declaration.attrs.get('tokens',()):candidates.append(method)
        if len(candidates)==1:
            candidates[0].attrs['functional']=True
            candidates[0].attrs['functional_basis']='direct-java-single-abstract-method'
