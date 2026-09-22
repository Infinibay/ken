"""Occurrence-level consumers of an evaluated value, never historical binding flow.

The index publishes witnessed uses. It does not certify a closed inventory across
heap aliases, callbacks or interprocedural flow: an additional uncertain candidate
preserves that distinction for selection, negation and downstream constraints.
"""
from collections import defaultdict
from dataclasses import replace
from hashlib import sha256
import json

KINDS = frozenset({'argument','return','assignment','condition','operand','receiver'})


def compile_usage(clause,bound):
    from .graph import fail,matcher
    filters=[]
    seen=set()
    for prop in clause.blocks[0]:
        if prop.kind!='property' or prop.name not in {'kind','position','owner','consumer','path','line'}:
            fail('usages accepts kind, position, owner, consumer, path and line',prop)
        if prop.name in seen:fail('duplicate usage property',prop)
        seen.add(prop.name)
        value=prop.expressions[0]
        if prop.name=='kind':
            if value.kind=='name':value=replace(value,kind='literal',value=json.dumps(value.value))
            values=value.args if value.kind=='list' else (value,)
            if not values or any(v.kind!='literal' or json.loads(v.value) not in KINDS for v in values):
                fail('unknown usage kind',prop)
        if prop.name in ('position','line'):
            if value.kind!='literal' or not value.value.isdigit():fail('usage position/line requires a nonnegative integer',prop)
        if value.kind=='role':
            if prop.name not in ('owner','consumer') or value.value not in bound:
                fail('usage owner/consumer requires a selected role',prop)
            filters.append((prop.name,'role','$'+value.value))
        else:
            op,text=matcher(value)
            filters.append((prop.name,op,text))
    return ('$'+clause.name,'$'+clause.role,tuple(filters))


class Usages:
    RELATIONS={'ARGUMENT_VALUE_ORIGIN':'argument','RETURN_ORIGIN':'return',
               'ASSIGNMENT_ORIGIN':'assignment','READ_ORIGIN':'condition',
               'VALUE_DEPENDS_ON':'operand'}

    def __init__(self,index,tick):
        self.index,self.tick=index,tick
        self.operations={o.id:o for o in index.ir.operations}
        self.children=defaultdict(list)
        self.spans=defaultdict(list)
        self.call_nodes={f.object:f.subject for f in index.rows('SYNTAX_NODE')
                         if f.subject in index.ir.entities and index.ir.entities[f.subject].kind=='CALL'}
        for op in index.ir.operations:
            self.children[op.parent].append(op)
            owner=index.ir.entities.get(op.owner)
            if owner:self.spans[(owner.path,op.start,op.end)].append(op)
        self.by_origin=defaultdict(list)
        self.cache={}
        for relation,kind in self.RELATIONS.items():
            for fact in index.rows(relation):
                tick()
                self.by_origin[fact.object].append((kind,fact))
        from ken.structural.model import Fact
        for syntax,call in self.call_nodes.items():
            op=self.operations.get(syntax)
            consumer=self.read_consumer(op) if op else None
            if consumer is not None:
                kind,subject,position=consumer
                self.by_origin[call].append((kind,Fact(subject,'DIRECT_VALUE_USE',call,
                    {'modality':'must','position':position},[f'{index.ir.entities[call].path}:{op.line}'])))

    def source_operation(self,identifier):
        if identifier in self.operations:return self.operations[identifier]
        entity=self.index.ir.entities.get(identifier)
        if entity is None:return None
        candidates=self.spans.get((entity.path,entity.attrs.get('start_byte'),entity.attrs.get('end_byte')),())
        exact=[op for op in candidates if op.native_kind==entity.attrs.get('native_kind')]
        return exact[0] if len(exact)==1 else candidates[0] if len(candidates)==1 else None

    def read_consumer(self,op):
        """Classify the direct consumer, not an arbitrary ancestor condition.

        In if f(x), x is an argument of f; only f's result is the condition.
        Stop at the first nontransparent expression so derived identity never
        leaks from an operand into its enclosing call/branch.
        """
        current=op
        seen=set()
        while current.parent in self.operations and current.id not in seen:
            seen.add(current.id)
            parent=self.operations[current.parent]
            if (current.role == 'object' and parent.kind == 'MEMBER'
                    and parent.role == 'function'):
                call = self.call_nodes.get(parent.parent)
                if call:
                    return 'receiver', call, None
                return None
            if parent.native_kind in ('argument_list','arguments'):
                args=sorted((o for o in self.children[parent.id] if 'comment' not in o.native_kind),key=lambda o:o.start)
                call=self.call_nodes.get(parent.parent)
                if call and current in args:return 'argument',call,args.index(current)
                return None
            operands=list(self.index.rows('OPERAND',parent.id))
            operand=next((f for f in operands if f.object==current.id),None)
            if operand is not None and parent.kind in ('BINARY','UNARY'):
                return 'operand',parent.id,operand.attrs.get('position')
            if parent.kind in ('BRANCH','LOOP'):
                if any(f.object==current.id for f in self.index.rows('CONTROL_CONDITION',parent.id)):
                    return 'condition',parent.id,None
                return None
            if parent.kind=='RETURN':return 'return',parent.id,None
            if parent.kind=='ASSIGN' and current.role in ('value','right'):
                return 'assignment',parent.id,None
            if parent.native_kind not in ('parenthesized_expression','condition_clause','argument','expression_list'):
                return None
            current=parent
        return None

    def unreachable(self,op):
        seen=set()
        current=op
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.attrs.get('execution')=='unreachable':return True
            parent=self.operations.get(current.parent)
            if parent is not None and parent.kind=='BRANCH' and current.role in ('consequence','alternative'):
                conditions=self.index.rows('CONTROL_CONDITION',parent.id)
                condition=self.operations.get(conditions[0].object) if len(conditions)==1 else None
                unwrapped=set()
                while condition is not None and condition.native_kind in ('parenthesized_expression','condition_clause') and condition.id not in unwrapped:
                    unwrapped.add(condition.id)
                    inner=[c for c in self.children[condition.id] if 'comment' not in c.native_kind]
                    condition=inner[0] if len(inner)==1 else None
                if condition is not None and condition.native_kind in ('true','false','boolean_literal'):
                    truth={'true':True,'True':True,'false':False,'False':False}.get(condition.attrs.get('text'))
                    if truth is not None and truth!=(current.role=='consequence'):return True
            current=parent
        return False

    def uses(self,value):
        if value in self.cache:return self.cache[value]
        origins={value}
        # RESULT links an occurrence to its evaluated value. This is identity,
        # unlike VALUE_DEPENDS_ON, which must never propagate to the new result.
        origins.update(f.subject for f in self.index.rows('RESULT',object=value) if f.object==value)
        collected={}
        for origin in origins:
            for kind,fact in self.by_origin.get(origin,()):
                self.tick()
                consumer=fact.subject
                position=fact.attrs.get('position')
                op=self.source_operation(consumer)
                if fact.relation=='READ_ORIGIN':
                    classified=self.read_consumer(op) if op else None
                    if classified is None:continue
                    kind,consumer,position=classified
                    op=self.source_operation(consumer)
                if kind=='operand' and op is not None:
                    consumer=op.id
                entity=self.index.ir.entities.get(consumer)
                if op is None and entity is None:continue
                owner=op.owner if op else entity.attrs.get('owner') if entity else None
                owner_entity=self.index.ir.entities.get(owner)
                if (op is not None and self.unreachable(op)
                        or entity is not None and entity.attrs.get('execution')=='unreachable'):
                    continue
                if kind in ('argument','operand') and not isinstance(position,int):
                    continue
                attributes={'kind':kind,'consumer':consumer,'owner':owner,
                            'path':entity.path if entity else owner_entity.path if owner_entity else None,
                            'line':op.line if op else entity.line if entity else None,
                            'position':position}
                if entity is not None and entity.kind == 'CALL':
                    attributes['consumer_name'] = entity.attrs.get('name', entity.name)
                key=(kind,consumer,position)
                uncertain=fact.attrs.get('modality')!='must'
                if kind=='argument':
                    arguments=[metadata.attrs for argument in self.index.rows('ARGUMENT',consumer)
                               for metadata in self.index.rows('ENTITY',argument.object)
                               if metadata.object=='ARGUMENT']
                    # Expanding a pack does not pass the pack value itself as a
                    # scalar argument, and later positions are unresolved.
                    if any(str(a.get('kind','')).startswith('spread') and
                           isinstance(a.get('position'),int) and a['position']<=position for a in arguments):
                        uncertain=True
                if key not in collected or collected[key][1] and not uncertain:
                    collected[key]=(attributes,uncertain,fact)
        result=[]
        for key,(attrs,uncertain,fact) in sorted(collected.items(),key=lambda item:str(item[0])):
            usage='usage:'+sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
            result.append((usage,attrs,uncertain,fact))
        self.cache[value]=tuple(result)
        return self.cache[value]


def match(executor,spec,row):
    from ken.structural.relational import Row,_compare
    value_role,usage_role,filters=spec
    value=row.bindings[value_role]
    if not hasattr(executor,'_usages'):
        executor._usages=Usages(executor.index,executor.tick)
        executor.usage_metadata={}
    for usage,attrs,uncertain,fact in executor._usages.uses(value):
        executor.tick()
        if usage_role in row.bindings and row.bindings[usage_role]!=usage:continue
        metadata_unknown=False
        rejected=False
        for name,mode,text in filters:
            if attrs.get(name) is None and name!='position':
                metadata_unknown=True
            elif not (attrs.get(name)==row.bindings[text] if mode=='role' else _compare(attrs.get(name),mode,text)):
                rejected=True;break
        if rejected:continue
        executor.usage_metadata[usage]=attrs
        evidence={'usage':usage,**attrs,'value':value,'relation':fact.relation,
                  'source':fact.evidence,'inventory':'open'}
        yield Row({**row.bindings,usage_role:usage},row.evidence+[evidence],
                  row.unknown|({'usage_origin_may'} if uncertain else set())
                  |({'usage_metadata_unknown'} if metadata_unknown else set()))
    # Unknown uses are not made into a negative merely because no witness was
    # modelled. Nor may an exhaustive count be inferred from the known witnesses.
    unknown='@unknown:usage:'+value
    if usage_role not in row.bindings or row.bindings[usage_role].startswith('@unknown:'):
        executor.usage_metadata[unknown]={}
        yield Row({**row.bindings,usage_role:unknown},row.evidence+[{'value':value,'usage_inventory':'open'}],
                  row.unknown|{'usage_inventory_open'})
