"""Conservative primitive-boolean accreditation for source call results.

True means the static model accredits a primitive bool result, not that the
runtime value is true. False means not proven; nullable/boxed/async/ambiguous
results are deliberately excluded. Function-type syntax is read from AST nodes.
"""
from collections import defaultdict


class BooleanResults:
    def __init__(self,index,check=lambda:None):
        self.index,self.check=index,check
        self.operations={o.id:o for o in index.ir.operations}
        self.children=defaultdict(list)
        self.spans=defaultdict(list)
        for op in index.ir.operations:
            self.children[op.parent].append(op)
            self.spans[(op.start,op.end)].append(op)
        self.shadowed_bool_paths={e.path for e in index.ir.entities.values() if e.name=='bool'}
        for op in index.ir.operations:
            if op.native_kind in ('type_spec','type_alias') and any(
                child.role=='name' and child.attrs.get('text')=='bool' for child in self.children[op.id]):
                owner=index.ir.entities.get(op.owner)
                if owner is not None:self.shadowed_bool_paths.add(owner.path)
        self.call_operations=defaultdict(set)
        for fact in index.rows('SYNTAX_NODE'):
            entity=index.ir.entities.get(fact.subject)
            if entity is not None and entity.kind=='CALL':
                self.call_operations[fact.object].add(fact.subject)
        self.memo={}

    def rows(self,relation,subject):
        self.check()
        return self.index.rows(relation,subject)

    def is_boolean(self,call_id):
        self.check()
        if call_id in self.memo:return self.memo[call_id]
        entity=self.index.ir.entities.get(call_id)
        if entity is None or entity.kind!='CALL':
            candidates=self.call_operations.get(call_id,())
            if len(candidates)!=1:return False
            call_id=next(iter(candidates))
        if self.rows('MAY_TARGET',call_id):return False
        targets={f.object for relation in ('TARGET','DECLARED_TARGET') for f in self.rows(relation,call_id)}
        if targets:
            answer=len(targets)==1 and self.callable_return(next(iter(targets)))
        else:
            bindings={f.object for f in self.rows('CALLEE_VALUE',call_id)}
            answer=len(bindings)==1 and self.callback_return(next(iter(bindings)))
        self.memo[call_id]=answer
        return answer

    def primitive_reference(self,subject,relation,language):
        refs={f.object for f in self.rows(relation,subject)}
        if len(refs)!=1:return False
        ref=next(iter(refs))
        kinds={f.object for f in self.rows('TYPE_KIND',ref)}
        natives={f.object for f in self.rows('TYPE_NATIVE',ref)}
        primitive={'java':'boolean','typescript':'boolean','csharp':'bool','cpp':'bool','go':'bool','rust':'bool','python':'bool'}
        if kinds!={'bool'} or natives!={primitive.get(language)}:return False
        if language in ('go','python'):
            entity=self.index.ir.entities[subject]
            if entity.path in self.shadowed_bool_paths:return False
        return True

    def callable_return(self,callable_id):
        entity=self.index.ir.entities.get(callable_id)
        if entity is None or entity.kind!='CALLABLE':return False
        if any(entity.attrs.get(key) for key in ('async_','async','generator')):return False
        if self.rows('HAS_YIELD',callable_id):return False
        return self.primitive_reference(callable_id,'RETURN_TYPE_REF',entity.attrs.get('language'))

    def transparent(self,node):
        while node.native_kind in ('type_annotation','parenthesized_type'):
            children=self.children[node.id]
            if len(children)!=1:return None
            node=children[0]
        return node

    def callback_return(self,binding_id):
        entity=self.index.ir.entities.get(binding_id)
        if entity is None or entity.kind!='PARAMETER':return False
        language=entity.attrs.get('language')
        if language not in ('go','typescript'):return False
        status=self.rows('STORAGE_WRITE_STATUS',binding_id)
        counts=self.rows('STORAGE_WRITE_COUNT',binding_id)
        if not status or any(f.object!='supported' for f in status) or len(counts)!=1 or counts[0].object!='0':return False
        declarations=[op for op in self.spans[(entity.attrs.get('start_byte'),entity.attrs.get('end_byte'))]
                      if op.native_kind==entity.attrs.get('native_kind')]
        if len(declarations)!=1:return False
        annotation=[op for op in self.children[declarations[0].id] if op.role=='type']
        if len(annotation)!=1:return False
        function=self.transparent(annotation[0])
        if function is None or function.native_kind!='function_type':return False
        results=[op for op in self.children[function.id] if op.role==('result' if language=='go' else 'return_type')]
        if len(results)!=1:return False
        result=self.transparent(results[0])
        if result is None:return False
        if language=='typescript':return result.native_kind=='predefined_type' and result.attrs.get('text')=='boolean'
        if entity.path in self.shadowed_bool_paths:return False
        return result.native_kind=='type_identifier' and result.attrs.get('text')=='bool'
