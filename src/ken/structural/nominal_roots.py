"""Unique roots of explicitly written, completely resolved nominal base graphs."""
from collections import defaultdict
from .model import IR


def nominal_roots(graph: IR) -> None:
    if graph.diagnostics:
        return
    supported={'python','javascript','typescript','java','csharp','cpp'}
    types={e.id for e in graph.entities.values() if e.kind in {'CLASS','INTERFACE'}
           and e.attrs.get('language') in supported}
    bases: dict[str,set[str]]=defaultdict(set)
    names: dict[str,set[str]]=defaultdict(set)
    for fact in graph.facts:
        if fact.relation=='BASE_NAME':names[fact.subject].add(fact.object)
        elif fact.relation=='SUBTYPE_OF':bases[fact.subject].add(fact.object)

    memo: dict[tuple[str,int],tuple[set[str],str]]={}

    def roots(unit: str, trail: frozenset[str]) -> tuple[set[str],str]:
        if unit in trail:return set(),'cycle'
        key=(unit,32-len(trail))
        if key not in memo:memo[key]=walk(unit,trail)
        return memo[key]

    def walk(unit: str, trail: frozenset[str]) -> tuple[set[str],str]:
        if len(trail)>=32:return set(),'depth-bound'
        if unit not in types:return set(),'unsupported-type'
        if len(names[unit])!=len(bases[unit]):return set(),'unresolved-bases'
        if not bases[unit]:return {unit},''
        result: set[str]=set()
        for base in sorted(bases[unit]):
            found,reason=roots(base,trail|{unit})
            if reason:return set(),reason
            result.update(found)
            if len(result)>1:return set(),'multiple-roots'
        return result,''

    for unit in sorted(types):
        found,reason=roots(unit,frozenset());entity=graph.entities[unit]
        graph.add(unit,'NOMINAL_ROOT_STATUS','unsupported' if reason else 'supported',
                  analysis='explicit-nominal-roots/1',reason=reason)
        if not reason and len(found)==1:
            graph.add(unit,'NOMINAL_ROOT',next(iter(found)),f'{entity.path}:{entity.line}',
                      basis='explicit-resolved-bases',analysis='explicit-nominal-roots/1')
