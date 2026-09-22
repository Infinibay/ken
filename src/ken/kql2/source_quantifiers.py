"""Quantification over source declaration inventories with explicit closure.

The quantifier is independent of catalog patterns. Constructor declarations are
its first domain; allocation counts and runtime constructibility are unrelated.
"""
from dataclasses import dataclass


def compile_requirement(clause):
    from .graph import fail
    properties=[]
    for prop in clause.blocks[0]:
        if prop.kind!='property' or prop.name!='visibility' or len(prop.expressions)!=1:
            fail('quantified constructor constraints currently support visibility',prop)
        value=prop.expressions[0]
        expected=value.value.strip('"') if value.kind in ('name','literal') else ''
        if expected not in ('private','public','protected','internal','package'):
            fail('quantified visibility requires a visibility name',prop)
        if properties:fail('duplicate quantified visibility property',prop)
        properties.append(('visibility',expected))
    if clause.flags[0]=='one':
        if clause.name not in ('allocation','dispatch') or properties:
            fail('one quantifies the resolved allocation or dispatch count only',clause)
        witness = clause.flags[1] if len(clause.flags)>1 else ''
        extra = (('named','$'+witness),) if witness else ()
        return ('one',clause.name,'$'+clause.role,(('count','1'),)+extra)
    if clause.flags[0]=='every' and not properties:
        fail('every constructor requires a declaration constraint',clause)
    return (clause.flags[0],clause.name,'$'+clause.role,tuple(properties))


@dataclass(frozen=True)
class Inventory:
    members: tuple[str,...]
    complete: bool


def _spelling(value,index):
    """The name a selected callable publishes: its own name, else its ENTITY row."""
    name=getattr(value,'name',None)
    identity=getattr(value,'local_id',None) or (value if isinstance(value,str) else None)
    entity=index.ir.entities.get(identity) if identity else None
    if not name and entity is not None:
        name=entity.attrs.get('name')
    if not name and identity:
        name=next((fact.attrs.get('name') for fact in index.rows('ENTITY',identity)
                   if fact.attrs.get('name')),None)
    return name or None


class Declarations:
    """Per-execution memo of declared members; no whole-project reparse."""
    def __init__(self,index,tick):
        self.index,self.tick=index,tick
        self.cache={}

    def inventory(self,kind,owner,spelling=None):
        key=(kind,owner,spelling)
        if key in self.cache:return self.cache[key]
        if kind=='allocation':
            # One decisive row per selected type: the number of resolved sites.
            rows=self.index.rows('RESOLVED_ALLOCATION_COUNT',owner)
            members=tuple(str(row.object) for row in rows)
            complete=(len(rows)==1 and rows[0].attrs.get('basis')=='explicit-resolved-sites')
            result=Inventory(members,complete)
            self.cache[key]=result
            return result
        if kind!='constructor' and kind!='dispatch':raise ValueError('unsupported quantified declaration domain')
        if kind=='dispatch':
            # One decisive row per selected callable: how many call sites its own body
            # dispatches. The counted spelling is the declaration's own name, or the
            # ``named`` witness when one is given. The structured CFG enumerates
            # that body's statements, so a callable without the witness stays open, and
            # a call occurrence whose callee spelling is unknown cannot be counted.
            name=spelling or _spelling(owner,self.index)
            count=0
            known=bool(name)
            for call in self.index.rows('HAS_CALL',owner):
                self.tick()
                if call.attrs.get('execution')!='possible':continue
                entity=self.index.ir.entities.get(call.object)
                callee=entity.attrs.get('name') if entity is not None else None
                if not isinstance(callee,str) or not callee:
                    known=False
                    break
                if callee==name:count+=1
            statuses=self.index.rows('CFG_STATUS',owner)
            complete=(known and len(statuses)==1 and statuses[0].object=='structured'
                      and statuses[0].attrs.get('level')=='statement')
            if not complete:
                self.cache[key]=Inventory((),False)
                return self.cache[key]
            members=(str(count),)
            result=Inventory(members,True)
            self.cache[key]=result
            return result
        members=[]
        for fact in self.index.rows('HAS_METHOD',owner):
            self.tick()
            entity=self.index.ir.entities.get(fact.object)
            if entity is not None and entity.attrs.get('instance_constructor') is True:
                members.append(entity.id)
        members=tuple(sorted(set(members)))
        statuses=self.index.rows('CONSTRUCTOR_INVENTORY',owner)
        # Cross-check the inventory cardinality instead of trusting stale or
        # partial declaration rows as a closed universe.
        complete=(len(statuses)==1 and statuses[0].object=='supported'
                  and statuses[0].attrs.get('explicit')==len(members))
        result=Inventory(members,complete)
        self.cache[key]=result
        return result

    def satisfies(self,member,properties):
        if properties and properties[0][0]=='count':
            self.tick()
            try:return int(member)==int(properties[0][1])
            except ValueError:return None
        entity=self.index.ir.entities[member]
        for name,expected in properties:
            self.tick()
            if name=='visibility':
                if entity.attrs.get('visibility_status')!='supported':return None
                actual=entity.attrs.get('visibility')
                if actual not in ('private','public','protected','internal','package','internal protected','private protected'):return None
                if actual!=expected:return False
        return True


def quantify(quantifier,values,complete):
    """Three-valued finite-domain quantification; decisive witnesses win."""
    if quantifier=='exists':
        if any(value is True for value in values):return True
        return False if complete and all(value is False for value in values) else None
    if quantifier=='every':
        if any(value is False for value in values):return False
        return True if complete and all(value is True for value in values) else None
    if quantifier=='one':
        if any(value is None for value in values):return None
        if sum(value is True for value in values)==1:return True
        return False if complete else None
    raise ValueError(quantifier)


def match(executor,spec,row):
    from ken.structural.relational import Row
    quantifier,kind,owner_role,properties=spec
    if not hasattr(executor,'_source_declarations'):
        executor._source_declarations=Declarations(executor.index,executor.tick)
    declarations=executor._source_declarations
    owner=row.bindings[owner_role]
    witness=next((value for name,value in properties if name=='named'),None)
    spelling=_spelling(row.bindings[witness],executor.index) if witness else None
    inventory=declarations.inventory(kind,owner,spelling)
    values=tuple(declarations.satisfies(member,properties) for member in inventory.members)
    truth=quantify(quantifier,values,inventory.complete)
    if truth is False:return
    missing=set(row.unknown)
    if truth is None:missing.add('source_quantifier:'+kind+':incomplete_inventory')
    evidence={'subject':owner,'relation':'source_quantifier','object':quantifier,
              'declaration':kind,'members':list(inventory.members),'complete':inventory.complete,
              'constraints':dict(properties)}
    yield Row(row.bindings,row.evidence+[evidence],missing)
