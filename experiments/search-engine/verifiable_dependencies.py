"""Visible calls and their source-authenticated, same-file lexical definitions.

This is a context dependency, not a claim about runtime dispatch, execution,
purity, or the absence of effects. Unresolved/ambiguous calls add no evidence.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from ken.retrieval.model import EntityKey
from ken.structural.frontend import LANGUAGES, lower_source
from ken.structural.semantic import link_project

from verifiable_pieces import EvidenceCardBuilder, SYMBOL_KINDS, entity_id, terms, validate_card


@dataclass(frozen=True)
class LocalCall:
    caller: EntityKey
    callee: EntityKey
    start_line: int
    end_line: int

    def provenance(self):
        return {'kind':'same_file_lexical_call','caller':self.caller.to_dict(),
                'call_start_line':self.start_line,'call_end_line':self.end_line}


class LocalCallEvidence:
    """Cache compact resolved-call edges; discard the full per-file syntax IR."""
    def __init__(self,catalog):
        self.catalog=catalog
        self._files={}
        self._by_name=defaultdict(list)
        self._extents={}
        for key in catalog.owners:
            if key.kind in SYMBOL_KINDS and key.qualname:
                self._by_name[(key.path,key.qualname.split('.')[-1])].append(key)
                self._extents[key]=catalog.extent(key)

    def _owner(self,node):
        candidates=[key for key in self._by_name.get((node.path,node.name),())
            if self._extents[key][0]<=node.line<=node.end_line<=self._extents[key][1]]
        if not candidates:return None
        width=lambda key:self._extents[key][1]-self._extents[key][0]
        candidates.sort(key=lambda key:(width(key),entity_id(key)))
        if len(candidates)>1 and width(candidates[0])==width(candidates[1]):return None
        return candidates[0]

    def _resolve(self,path):
        source=(self.catalog.root/path).read_bytes()
        if hashlib.sha256(source).hexdigest()!=self.catalog.hashes[path]:
            raise ValueError('source changed before local call resolution')
        if path in self._files:return self._files[path]
        language=LANGUAGES.get(Path(path).suffix)
        if language not in {'python','javascript','typescript'}:
            self._files[path]={};return self._files[path]
        graph=link_project([lower_source(source,language,path)])
        owners={node.id:self._owner(node) for node in graph.entities.values() if node.kind=='CALLABLE'}
        callers={f.object:f.subject for f in graph.facts if f.relation=='HAS_CALL'}
        targets=defaultdict(set);uncertain=set()
        for fact in graph.facts:
            if fact.relation=='TARGET':targets[fact.subject].add(fact.object)
            elif fact.relation=='MAY_TARGET':uncertain.add(fact.subject)
        result=defaultdict(list)
        for call_id,target_ids in targets.items():
            if len(target_ids)!=1 or call_id in uncertain or call_id not in callers:continue
            call=graph.entities[call_id];caller=graph.entities.get(callers[call_id])
            callee=graph.entities[next(iter(target_ids))]
            if (caller is None or caller.kind!='CALLABLE' or callee.kind!='CALLABLE'
                    or caller.path!=path or callee.path!=path):continue
            owner=owners[caller.id];target=owners[callee.id]
            if owner is None or target is None or owner==target:continue
            if not any(a<=call.line<=call.end_line<=b for a,b in self.catalog.owned_ranges(owner)):continue
            result[owner].append(LocalCall(owner,target,call.line,call.end_line))
        self._files[path]={key:tuple(sorted(set(edges),key=lambda e:(e.start_line,e.end_line,entity_id(e.callee))))
                           for key,edges in result.items()}
        return self._files[path]

    def for_owner(self,key):
        return self._resolve(key.path).get(key,())

    @staticmethod
    def visible(card,edge):
        lines={n for e in card['excerpts'] if 'dependency' not in e and
               e['path']==edge.caller.path and e['entity']==edge.caller.to_dict()
               for n in range(e['start_line'],e['end_line']+1)}
        return set(range(edge.start_line,edge.end_line+1))<=lines

    def validate(self,card,excerpt,key):
        proof=excerpt['dependency']
        try:caller=EntityKey(path=excerpt['path'],**proof['caller'])
        except (KeyError,TypeError):raise ValueError('invalid dependency caller') from None
        edges=[edge for edge in self.for_owner(caller)
               if edge.callee==key and edge.provenance()==proof]
        if not edges:raise ValueError('unproven local dependency')
        if not any(self.visible(card,edge) for edge in edges):
            raise ValueError('dependency requires a visible call')


def enrich_card(card,query,catalog,dependencies):
    """Add direct local callees within spare capacity, keeping the primary piece."""
    if card is None:return None
    validate_card(card,catalog,dependencies=dependencies)
    result=deepcopy(card);builder=EvidenceCardBuilder(result,catalog)
    if not builder.remaining_lines or not builder.remaining_excerpts:return result
    callers={EntityKey(path=e['path'],**e['entity']) for e in card['excerpts']
             if e['entity'] is not None and 'dependency' not in e}
    edges=[edge for key in callers for edge in dependencies.for_owner(key)
           if dependencies.visible(card,edge)]
    q=terms(query)
    def priority(edge):
        source='\n'.join('\n'.join(catalog.lines[edge.callee.path][a-1:b])
                         for a,b in catalog.owned_ranges(edge.callee))
        return (-len(q&terms(source)),entity_id(edge.callee),edge.start_line,
                edge.end_line,entity_id(edge.caller))
    selected=set()
    for edge in sorted(edges,key=priority):
        if edge.callee in selected:continue
        selected.add(edge.callee)
        builder.definition(edge.callee,query,dependency=edge.provenance())
        if not builder.remaining_lines or not builder.remaining_excerpts:break
    validate_card(result,catalog,dependencies=dependencies)
    return result
