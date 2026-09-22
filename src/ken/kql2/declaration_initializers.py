"""Source-expression matches anchored to a binding's declaration initializer.

Nested allocations are not root values. Missing linkage is distinct from a known
literal/non-call root, and possible allocation evidence stays uncertain.
"""
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Initializer:
    binding: str
    assignment: str
    expression: str
    call: str | None
    unknown: frozenset[str] = frozenset()


class Initializers:
    def __init__(self,index,tick=lambda:None):
        self.index,self.tick=index,tick
        self.cache={}
        native=getattr(index,'operations',None)
        if native is not None and hasattr(index,'syntax_bounds'):
            from ken.structural_store.graph_source import Lookup

            self.operations=Lookup(lambda key: next(native(local_id=key),None)
                                   if key is not None else None,capacity=512)
            self.children=Lookup(self._native_children,capacity=128)
            self.calls=Lookup(self._native_calls,capacity=512)
            self.by_path=Lookup(self._native_assignments,capacity=16)
            self._assignments_by_path=None
            return
        self.operations={o.id:o for o in index.ir.operations}
        self.children=defaultdict(list)
        self.by_path=defaultdict(list)
        for op in index.ir.operations:
            self.children[op.parent].append(op)
            owner=index.ir.entities.get(op.owner)
            if owner is not None:self.by_path[owner.path].append(op)
        self.calls=defaultdict(set)
        for fact in index.rows('SYNTAX_NODE'):
            entity=index.ir.entities.get(fact.subject)
            if entity is not None and entity.kind=='CALL':self.calls[fact.object].add(fact.subject)

    def close(self):
        # Native Lookup wrappers hold bound methods; break that cycle and the
        # budget callback before releasing a query's adapters.
        self.tick=None
        self.index=None
        for name in ('operations','children','by_path','calls','_assignments_by_path'):
            self.__dict__.pop(name,None)
        self.cache.clear()

    def _native_children(self,parent):
        operation=self.operations.get(parent)
        if operation is None:return []
        # Syntax membership, not ownership: an initializer may contain a
        # lambda/arrow whose operations belong to another callable.
        result=[]
        for child in self.index.operations(region=operation):
            self.tick()
            if child.parent==parent:result.append(child)
        return result

    def _native_calls(self,expression):
        calls=set()
        for fact in self.index.rows('SYNTAX_NODE',object=expression):
            self.tick()
            entity=self.index.ir.entities.get(fact.subject)
            if entity is not None and entity.kind=='CALL':calls.add(fact.subject)
        return calls

    def _native_assignments(self,path):
        # Needed only when a declaration has no target link. Retain the
        # conservative missing-link audit, but read the indexed ASSIGN kind
        # once instead of materializing every project operation twice.
        if self._assignments_by_path is None:
            grouped=defaultdict(list)
            for operation in self.index.operations(kind='ASSIGN'):
                self.tick()
                owner=self.index.ir.entities.get(operation.owner)
                if owner is not None:grouped[owner.path].append(operation)
            self._assignments_by_path=grouped
        return self._assignments_by_path.get(path,[])

    def regions(self,binding):
        if binding in self.cache:return self.cache[binding]
        entity=self.index.ir.entities.get(binding)
        result=[]
        if entity is None or not entity.attrs.get('declared'):
            self.cache[binding]=();return ()
        start=entity.attrs.get('start_byte',-1)
        targets=list(self.index.rows('ASSIGNMENT_TARGET',object=binding))
        for target in targets:
            self.tick()
            op=self.operations.get(target.subject)
            if op is None:
                result.append(Initializer(binding,target.subject,'',None,frozenset({'initializer_operation_missing'})))
                continue
            owner=self.index.ir.entities.get(op.owner)
            if owner is not None and owner.path!=entity.path:continue
            if not op.start<=start<op.end or op.attrs.get('execution')=='unreachable':continue
            uncertain=set()
            if target.attrs.get('modality')=='may':uncertain.add('initializer_target_may')
            children=[o for o in self.children[op.id] if o.role in ('value','right') and 'comment' not in o.native_kind]
            if not children and entity.attrs.get('language')=='csharp' and op.native_kind=='variable_declarator':
                children=[o for o in self.children[op.id] if o.role!='name' and 'comment' not in o.native_kind]
            if not children and len(self.children[op.id])==1:
                # Some front ends wrap the value one level below the statement:
                # Go publishes ``var_declaration > var_spec`` where the wrapper
                # carries no ``value``/``right`` role of its own, so the
                # initializer expression is found inside the declaration spec.
                wrapper=self.children[op.id][0]
                if wrapper.native_kind in ('var_spec','short_var_declaration','const_spec'):
                    children=[o for o in self.children[wrapper.id] if o.role in ('value','right') and 'comment' not in o.native_kind]
            if len(children)!=1:
                result.append(Initializer(binding,op.id,'',None,frozenset(uncertain|{'initializer_expression_missing'})))
                continue
            expression=children[0]
            seen=set()
            while expression.native_kind in ('parenthesized_expression','parenthesized_list','expression_list'):
                if expression.id in seen:
                    uncertain.add('initializer_expression_cycle');break
                seen.add(expression.id)
                inner=[o for o in self.children[expression.id] if 'comment' not in o.native_kind]
                if len(inner)!=1:break
                expression=inner[0]
            calls=self.calls.get(expression.id,())
            call=next(iter(calls)) if len(calls)==1 else None
            if expression.kind=='CALL' and call is None:uncertain.add('initializer_call_link_missing')
            result.append(Initializer(binding,op.id,expression.id,call,frozenset(uncertain)))
        if not targets:
            # An initializer-shaped assignment with a missing target link is not
            # equivalent to a declaration that has no initializer at all.
            for op in self.by_path.get(entity.path,()):
                if op.kind=='ASSIGN' and op.start<=start<op.end:
                    result.append(Initializer(binding,op.id,'',None,frozenset({'initializer_target_missing'})))
        self.cache[binding]=tuple(result)
        return self.cache[binding]


def match(executor,spec,row):
    from ken.structural.relational import Row
    binding_role,mode,target_role,output_role=spec
    if not hasattr(executor,'_declaration_initializers'):
        executor._declaration_initializers=Initializers(executor.index,executor.tick)
    binding=row.bindings[binding_role]
    for region in executor._declaration_initializers.regions(binding):
        executor.tick()
        missing=set(row.unknown)|set(region.unknown)
        target=row.bindings[target_role]
        if region.call is None:
            if not region.unknown:continue  # Known non-call expression.
        elif mode=='construct':
            allocations=list(executor.index.rows('ALLOCATES_TYPE',region.call))
            matching=[f for f in allocations if f.object==target]
            if matching:
                if all(f.attrs.get('modality')=='may' for f in matching):missing.add('initializer_allocation_may')
            elif allocations:continue  # A known allocation of another type.
            elif executor.index.ir.entities[region.call].attrs.get('construction'):
                missing.add('initializer_allocation_missing')
            else:continue  # A known ordinary call, not a root construction.
        elif region.call!=target:continue
        if region.call is not None and output_role in row.bindings and row.bindings[output_role]!=region.call:continue
        bindings=dict(row.bindings)
        if output_role and output_role not in bindings:
            bindings[output_role]=region.call or '@unknown:initializer:'+binding
        yield Row(bindings,row.evidence+[{'subject':region.assignment,'relation':'source_initializer','object':region.expression}],missing)
