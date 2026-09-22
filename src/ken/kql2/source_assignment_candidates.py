"""Necessary assignment candidates; BODY still verifies execution and effects.

Only a positive straight conjunction before its first BODY is eligible. Unknown
CFG coverage is never turned into a negative by this optimization.
"""


class AssignmentCandidates:
    def __init__(self,index,check):
        self.index=index
        self.check=check
        self.pairs=None
        self.cache={}
        self.incomplete=set()

    @staticmethod
    def pattern(nodes):
        parameters=set()
        for node in nodes:
            if node.kind=='fact':
                fact=node.value
                if fact.relation=='ENTITY' and fact.object in ('PARAMETER','"PARAMETER"'):
                    parameters.add(fact.subject)
            elif node.kind=='source_body':
                pattern=node.value
                for clause in pattern.clauses:
                    if clause.kind!='assign' or clause.name!='=':
                        continue
                    left,right=clause.expressions
                    if left.kind=='role' and right.kind=='role' and '$'+right.value in parameters:
                        return ('$'+pattern.owner,'$'+left.value,'$'+right.value)
                return None
            elif node.kind not in ('source_type','source_receiver','where','different'):
                return None
        return None

    def allows(self,spec,bindings):
        owner,left,right=(bindings.get(role) for role in spec)
        if owner is None:
            return True
        key=(owner,left,right)
        if key in self.cache:
            return self.cache[key]
        status=self.index.rows('CFG_STATUS',owner)
        if not status or any(f.object!='structured' for f in status):
            return True
        if self.pairs is None:
            from collections import defaultdict
            self.pairs=defaultdict(set)
            operations={operation.id:operation for operation in self.index.ir.operations}
            for target in self.index.rows('ASSIGNMENT_TARGET'):
                self.check()
                operation=operations.get(target.subject)
                if operation is None:
                    continue
                values=self.index.rows('ASSIGNMENT_VALUE',target.subject)
                if not values:
                    self.incomplete.add(operation.owner)
                for value in values:
                    candidates={value.object}
                    entity=self.index.ir.entities.get(value.object)
                    if entity is not None and entity.kind=='MEMBER':
                        candidates.update(f.object for f in self.index.rows('FLOWS_TO',value.object))
                    self.pairs[operation.owner].update((target.object,candidate) for candidate in candidates)
        if owner in self.incomplete:
            return True
        found=False
        for place,value in self.pairs.get(owner,()):
            self.check()
            if (left is None or left==place) and (right is None or right==value):
                found=True
                break
        self.cache[key]=found
        return found

    def domain(self,spec,bindings,role):
        owner=bindings.get(spec[0])
        if owner is None or role not in spec[1:]:
            return None
        status=self.index.rows('CFG_STATUS',owner)
        if not status or any(f.object!='structured' for f in status):
            return None
        # Initialize the pair index and keep unknown coverage out of pruning.
        self.allows(spec,bindings)
        if owner in self.incomplete:
            return None
        left,right=bindings.get(spec[1]),bindings.get(spec[2])
        return {place if role==spec[1] else value for place,value in self.pairs.get(owner,())
                if (left is None or left==place) and (right is None or right==value)}
