"""Conservative callable-local receiver escape summary for source selectors.

This proves absence only for inventoried, supported source uses. It deliberately
has no heap, dynamic reflection, or whole-program alias proof.
"""
from collections import defaultdict


class ReceiverEffects:
    def __init__(self, index, tick):
        self.index, self.tick = index, tick
        native = getattr(index, 'operations', None)
        if native is not None:
            from ken.structural_store.graph_source import Lookup

            # A receiver summary belongs to one callable. Native owner/id
            # indexes also preserve parents across nested callable boundaries.
            self.operations = Lookup(lambda key: next(native(local_id=key), None)
                                     if key is not None else None, capacity=256)
            self.owned = Lookup(lambda owner: list(native(owner=owner)), capacity=16)
        else:
            self.operations = {o.id: o for o in index.ir.operations}
            self.owned = defaultdict(list)
            for op in index.ir.operations:
                tick(); self.owned[op.owner].append(op)
        self.cache = {}

    def rows(self, relation, subject):
        for fact in self.index.rows(relation, subject):
            self.tick()
            if fact.subject == subject:
                yield fact

    def summarize(self, owner, receiver):
        key = owner, receiver
        if key in self.cache:
            return self.cache[key]
        self.cache[key] = None  # recursive invocation is not a proof
        status = list(self.rows('CFG_STATUS', owner))
        if not status or any(f.object != 'structured' for f in status):
            return None
        ops = self.owned.get(owner, ())
        entity = self.index.ir.entities.get(receiver)
        names = {'this', 'self'}
        if entity and entity.name:
            names.add(entity.name)
        uncertain = False
        declaration = self.index.ir.entities.get(owner)
        if declaration and declaration.attrs.get('instance_constructor'):
            for containing in self.rows('IN_TYPE',owner):
                nominal_targets = [self.index.ir.entities.get(f.object)
                                   for f in self.rows('SUBTYPE_OF',containing.object)]
                for base in self.rows('BASE_NAME',containing.object):
                    # The inheritance resolver, not a global spelling search,
                    # must accredit this nominal base. Interfaces have no
                    # instance constructor; classes and unresolved bases do.
                    # Qualified/generic spellings remain conservative unless an
                    # exact nominal name is available in the resolved entity.
                    resolved = [target for target in nominal_targets if target and
                                (target.name == base.object or
                                 target.attrs.get('qualified_name') == base.object)]
                    if len(resolved) != 1 or resolved[0].kind != 'INTERFACE':
                        uncertain = True
        # An argument/return/storage transfer of the receiver crosses its local
        # receiver role. Aliases are conservatively unknown instead of historical
        # propagation that could falsely prove absence after a redefinition.
        for op in ops:
            self.tick()
            if op.native_kind == 'explicit_constructor_invocation':
                receiver_tokens = [child.attrs.get('text') for child in ops if child.parent == op.id and child.role == 'constructor']
                if receiver_tokens != ['this']:
                    uncertain = True  # base-constructor effects are not modeled
            for rel in ('ASSIGNMENT_VALUE','RETURN_OPERAND'):
                if any(f.object == receiver for f in self.rows(rel, op.id)):
                    uncertain = True
            if op.kind != 'CALL':
                continue
            calls = list(self.index.rows('SYNTAX_NODE', object=op.id))
            for link in calls:
                self.tick()
                if link.object != op.id:
                    continue
                call = link.subject
                callable_entity = self.index.ir.entities.get(call)
                if callable_entity and callable_entity.name in ('eval','exec','execfile','compile','Function'):
                    uncertain = True  # reflective execution may refer to receiver textually
                for argument in self.rows('ARGUMENT', call):
                    if any(f.object == receiver for f in self.rows('VALUE', argument.object)):
                        self.cache[key] = True
                        return True
                if any(f.object == receiver for f in self.rows('RECEIVER',call)):
                    uncertain = True
        # Audit each spelling of the receiver as well, including unmodelled
        # containers/captures. Only using it as a member's base is locally safe;
        # calls on that base were checked above. No text-matching API model.
        for op in ops:
            if op.attrs.get('text') not in names:
                continue
            parent = self.operations.get(op.parent)
            if parent and parent.kind == 'MEMBER' and op.role in ('object','argument','operand','value'):
                continue
            if op.role in ('name','parameter') or (parent and parent.native_kind in ('parameters','parameter_list')):
                continue
            # A leading Java constructor delegation is checked recursively.
            if parent and parent.native_kind == 'explicit_constructor_invocation':
                delegated = []
                for link in self.index.rows('SYNTAX_NODE', object=parent.id):
                    self.tick()
                    if link.object == parent.id:
                        delegated.extend(f.object for f in self.rows('TARGET',link.subject))
                        delegated.extend(f.object for f in self.rows('CONSTRUCTOR_TARGET',link.subject))
                if not delegated and op.attrs.get('text') == 'this':
                    # Java this() is statically bound to a zero-argument sibling
                    # constructor; no overload choice by names or product type.
                    invocation = [f.subject for f in self.index.rows('SYNTAX_NODE',object=parent.id) if f.object == parent.id]
                    if len(invocation) == 1 and not list(self.rows('ARGUMENT',invocation[0])):
                        for containing in self.rows('IN_TYPE',owner):
                            for member in self.rows('HAS_METHOD',containing.object):
                                target = self.index.ir.entities.get(member.object)
                                if target and target.attrs.get('instance_constructor') and target.attrs.get('language') == 'java':
                                    parameters = [f for f in self.rows('HAS_PARAMETER',target.id) if not f.attrs.get('receiver')]
                                    if not parameters:
                                        delegated.append(target.id)
                if len(set(delegated)) == 1 and self.summarize(delegated[0],receiver) is False:
                    continue
            uncertain = True
        # A nested callable may capture receiver without belonging to this owner.
        for nested in self.index.rows('OWNED_BY',object=owner):
            self.tick()
            if nested.object != owner:
                continue
            child = self.index.ir.entities.get(nested.subject)
            if child and child.kind == 'CALLABLE':
                uncertain = True
        self.cache[key] = None if uncertain else False
        return self.cache[key]
