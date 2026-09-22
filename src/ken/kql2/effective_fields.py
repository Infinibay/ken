"""Effective source field places, resolved by declaration and lexical ancestry.

Keep the context's access identity for BODY receiver matching; use the resolved
field declaration for metadata. Never identify fields across unrelated types.
"""
from collections import defaultdict
from types import SimpleNamespace


class EffectiveFields:
    def __init__(self, index, check):
        self.index,self.check=index,check
        self.fields=defaultdict(dict);self.bases=defaultdict(set);self.spellings=defaultdict(set)
        self.methods=defaultdict(set);self.cache={}
        for relation in ('HAS_FIELD','SUBTYPE_OF','BASE_NAME','HAS_METHOD'):
            for fact in index.rows(relation):
                check()
                entity=index.ir.entities.get(fact.object)
                if relation=='HAS_FIELD' and entity:
                    self.fields[fact.subject][entity.name]=entity.id
                elif relation=='SUBTYPE_OF':self.bases[fact.subject].add(fact.object)
                elif relation=='BASE_NAME':self.spellings[fact.subject].add(fact.object)
                elif relation=='HAS_METHOD' and entity:self.methods[fact.subject].add(entity.name)

    def visible(self,owner):
        if owner in self.cache:return self.cache[owner]
        chain=[];current=owner;unknown=''
        entities=self.index.ir.entities
        while current:
            self.check()
            if current in chain or len(chain)>=32:
                unknown='cyclic_or_deep_ancestry';break
            chain.append(current)
            if len(self.bases[current])!=len(self.spellings[current]):
                unknown='unresolved_ancestry';break
            bases=self.bases[current]
            language=entities[current].attrs.get('language') if current in entities else ''
            if language in ('java','csharp'):
                bases={base for base in bases if entities.get(base) and entities[base].kind=='CLASS'}
            if len(bases)>1:
                unknown='multiple_inheritance';break
            current=next(iter(bases),'')
        names=set(self.fields[owner])
        if not unknown:
            for ancestor in chain:names.update(self.fields[ancestor])
        result=[]
        for name in sorted(names):
            access=self.fields[owner].get(name)
            declaration=None;reason=unknown
            if not reason:
                for ancestor in chain:
                    candidate=self.fields[ancestor].get(name)
                    if name in self.methods[ancestor]:
                        reason='descriptor_or_method_shadow';break
                    if candidate is None:continue
                    entity=entities[candidate]
                    if entity.attrs.get('declared'):
                        if ancestor!=owner and (name.startswith('#') or name.startswith('__') and not name.endswith('__')
                                               or entity.attrs.get('visibility')=='private'):
                            reason='private_inherited_field';break
                        declaration=candidate;break
                if declaration is None and not reason:
                    declaration=access
            if access is None:access=declaration
            if access is not None:result.append((access,declaration,reason,tuple(chain)))
        self.cache[owner]=result
        return result


def match(executor,spec,row):
    from ken.structural.relational import Row,_compare
    from .source_execution import SourceSemantics
    from .source_types import matches
    from .values import is_unknown
    if not hasattr(executor,'_effective_fields'):
        executor._effective_fields=EffectiveFields(executor.index,executor.tick)
    owner_role,field_role,attrs,type_matcher,nominal_role,declaration_role=spec
    owner=row.bindings[owner_role]
    semantics=SourceSemantics(executor.index,executor.tick)
    for access,declaration,reason,chain in executor._effective_fields.visible(owner):
        executor.tick()
        if field_role in row.bindings and row.bindings[field_role]!=access:continue
        bindings={**row.bindings,field_role:access};unknown=set(row.unknown)
        entity=executor.index.ir.entities.get(declaration or access)
        if reason:unknown.add('effective_field:'+reason)
        if declaration_role:
            if declaration_role in bindings and declaration and bindings[declaration_role]!=declaration:continue
            bindings[declaration_role]=declaration or 'unknown:effective-field-declaration:'+access
        if not reason and not all(_compare(entity.name if name=='name' else entity.attrs.get(name),op,value)
                                  for name,op,value in attrs):continue
        if nominal_role:
            types={f.object for f in executor.index.rows('TYPE',declaration)} if declaration else set()
            if reason or not types:
                if nominal_role not in bindings:bindings[nominal_role]='unknown:effective-field-type:'+access
                unknown.add('effective_field:type_unknown')
            elif nominal_role in bindings:
                if bindings[nominal_role] not in types:continue
            elif len(types)==1:bindings[nominal_role]=next(iter(types))
            else:
                bindings[nominal_role]='unknown:effective-field-type:'+access
                unknown.add('effective_field:type_ambiguous')
        elif type_matcher is not None and not reason:
            accepted=matches(semantics.type_of(SimpleNamespace(local_id=declaration)),type_matcher)
            if accepted is False:continue
            if is_unknown(accepted):unknown.add('effective_field:type_unknown')
        yield Row(bindings,row.evidence+[{'effective_field':access,'declaration':declaration,
                                         'ancestry':chain,'basis':'lexical-field-declaration'}],unknown)
