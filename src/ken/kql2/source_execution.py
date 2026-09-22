"""Run the existing CFG BODY matcher against the current immutable graph.

Adapters expose stable source IDs, without SQLite copies, reparsing, or a second
project analysis. Per-owner indexes and matching budgets belong to one executor.
"""
from __future__ import annotations

from collections import defaultdict, OrderedDict
from dataclasses import replace
import json

from ken.structural_store import Node
from .body import BodyEngine
from .semantic import SemanticRelations
from .values import OperationValue, Unknown, is_unknown


class SourceView:
    def __init__(self, index):
        self.index = index
        self.nodes = {}
        self.owned = defaultdict(list)
        self.operations = defaultdict(list)
        self.entities = defaultdict(dict)
        owners = {f.object: f.subject for f in index.ir.facts
                  if f.relation in ('DECLARES', 'HAS_PARAMETER', 'HAS_FIELD', 'HAS_METHOD')}
        owners.update({f.subject: f.object for f in index.ir.facts if f.relation == 'OWNED_BY'})
        for i, entity in enumerate(index.ir.entities.values()):
            owner = owners.get(entity.id, entity.attrs.get('owner'))
            node = Node(i, 0, entity.id, entity.kind, entity.name, owner,
                        entity.line, entity.end_line, entity.path, entity.attrs.get('language', index.ir.language))
            self.nodes[entity.id] = node
            self.owned[owner].append(node)
            self.entities[owner][entity.id] = entity
        # Literal operands are not declarations. Attach their direct uses to
        # the owner's small view without scanning all project entities per BODY.
        for fact in index.ir.facts:
            if fact.relation in ('ARGUMENT', 'ASSIGNMENT_VALUE', 'RETURN_OPERAND', 'OPERAND'):
                subject = index.ir.entities.get(fact.subject)
                if subject is not None:
                    owner = subject.attrs.get('owner', owners.get(fact.subject))
                    for value in index.rows('VALUE', fact.object):
                        if value.object in index.ir.entities:
                            self.entities[owner][value.object] = index.ir.entities[value.object]
        for op in index.ir.operations:
            self.operations[op.owner].append(op)
            owner=self.nodes.get(op.owner)
            if owner is not None and op.id not in self.nodes:
                self.nodes[op.id]=Node(0,owner.unit,op.id,'OPERATION','',owner.local_id,
                    op.line,op.line,owner.path,owner.language)
        for fact in index.rows('INSTANCE_RECEIVER'):
            owner = self.nodes.get(fact.subject)
            if owner is not None and fact.object not in self.nodes:
                self.nodes[fact.object] = Node(0,owner.unit,fact.object,'RECEIVER','this',owner.local_id,
                    owner.line,owner.end_line,owner.path,owner.language)

    def scan(self, snapshot, *, owner):
        return iter(self.owned[owner.local_id])

    def properties(self, node):
        entity = self.index.ir.entities.get(node.local_id)
        return {**(entity.attrs if entity is not None else {}),
                'name': node.name, 'path': node.path, 'language': node.language}


class SourceSemantics(SemanticRelations):
    def __init__(self, index, check):
        self.index, self.check = index, check
        self.types = {}

    def facts(self, relation, subject):
        self.check()
        if relation == 'ARGUMENT':
            # The public graph has argument occurrences; BODY consumes the raw
            # per-occurrence operand contract. Restore it losslessly here.
            from ken.structural.model import Fact
            result = []
            for argument in self.index.rows(relation, subject):
                attrs = next((f.attrs for f in self.index.rows('ENTITY', argument.object)), {})
                for value in self.index.rows('VALUE', argument.object):
                    loads = list(self.index.rows('LOADED_FROM', value.object))
                    entity = self.index.ir.entities.get(value.object)
                    origin = entity.attrs.get('origin') if entity else None
                    raw = loads[0].object if len(loads) == 1 else origin if origin in self.index.ir.entities else value.object
                    result.append(Fact(subject, relation, raw, attrs, argument.evidence))
            return result
        # A disk-backed posting list has an explicit count operation. Iterating
        # directly avoids list() requesting a separate SQL COUNT length hint.
        return [fact for fact in self.index.rows(relation, subject)]

    def facts_to(self, relation, object):
        # Reverse lookup for a fact a body clause reads from its object side, such as
        # ``DISCARDS_RESULT(statement, call)``. The ARGUMENT restoration above is
        # subject-indexed; every other relation is read straight from the index.
        self.check()
        return [fact for fact in self.index.rows(relation, object=object)]


class IndexedBodyEngine(BodyEngine):
    def source_unit(self, unit, owner):
        view = self.store
        if owner is None:
            # The owner-scoped view omits the sub-tree of a nested function expression
            # (lambda, arrow, func literal), which is a separate callable and therefore
            # owns its own operations. A pattern that must see such an operation as the
            # *value* of an enclosing statement reads it through the unit-wide view.
            return replace(view.index.ir, facts=[], capabilities=set(), diagnostics=[], relations=set())
        return replace(view.index.ir, operations=view.operations[owner], entities=view.entities[owner],
                       facts=[], capabilities=set(), diagnostics=[], relations=set())


class _PatternKey:
    """Cache an immutable plan's structural hash within one execution.

    Retain the plan so identity lookups cannot collide with reused object IDs.
    Structural equality still shares matches between equal, distinct plans;
    this execution-only wrapper does not change the compiled artifact schema.
    """

    __slots__ = ("pattern", "value")

    def __init__(self, pattern):
        self.pattern = pattern
        self.value = hash(pattern)

    def __hash__(self):
        return self.value

    def __eq__(self, other):
        return isinstance(other, _PatternKey) and self.pattern == other.pattern


class SourceExecutor:
    def __init__(self, executor):
        from ken.structural.query import _regex
        self.executor = executor
        self.view = executor.resources.source_view
        # Per-execution memoization only: irrelevant outer joins must not rerun
        # the same BODY. Bound input identities include seeded output roles.
        self._inputs = {}
        self._patterns = {}
        self._matches = OrderedDict()
        def regex(text, expression):
            pattern, flags = expression.value[1:].rsplit('/', 1)
            return bool(_regex(('(?'+flags+')' if flags else '') + pattern).search(text))
        def evaluate(expr, bindings):
            from ken.structural.relational import _compare
            if expr.kind == 'role':
                return bindings.get(expr.value, Unknown('unbound_source_role'))
            if expr.kind == 'literal':
                return json.loads(expr.value)
            if expr.kind == 'member':
                value = evaluate(expr.args[0], bindings)
                if isinstance(value, Node):
                    return getattr(value, expr.value, self.view.properties(value).get(expr.value, Unknown('attribute_missing')))
                return getattr(value, expr.value, Unknown('attribute_missing'))
            if expr.kind == 'binary':
                a, b = (evaluate(arg, bindings) for arg in expr.args)
                if is_unknown(a) or is_unknown(b):
                    return Unknown('source_condition_unknown')
                if expr.value == 'and':
                    return a is True and b is True
                if expr.value == 'or':
                    return a is True or b is True
                if expr.value in ('==', '!=', '<', '>', '<=', '>='):
                    return _compare(a, {'==':'literal', '!=':'not_literal'}.get(expr.value, expr.value), str(b))
            return Unknown('source_condition_unsupported')
        self.engine = IndexedBodyEngine(self.view, 0, SourceSemantics(executor.index, executor.tick),
                                        executor.tick, regex, evaluate)
        self.engine.units = executor.resources.body_units
        self.engine.contexts = executor.resources.body_contexts

    def close(self):
        # The recursive expression evaluator closes over this adapter, and its
        # budget callbacks reference the owning Executor. Sever those links so
        # finished queries cannot retain another full SourceView until a global
        # cyclic collection walks the entire repository graph.
        self._inputs.clear()
        self._patterns.clear()
        self._matches.clear()
        if self.executor._owns_resources:
            self.engine.units.clear()
            self.engine.contexts.clear()
        self.engine.store = None
        self.engine.semantic.index = None
        self.engine.semantic.check = None
        self.engine.check = None
        self.engine.evaluate = None
        self.engine = self.executor = self.view = None

    def match(self, pattern, row):
        from ken.structural.relational import Row
        self.executor.tick()
        pattern_key = self._patterns.get(id(pattern))
        if pattern_key is None:
            pattern_key = self._patterns[id(pattern)] = _PatternKey(pattern)
        if pattern_key not in self._inputs:
            roles = {pattern.owner}
            def expression(expr):
                if expr.kind == 'role':
                    roles.add(expr.value)
                for child in expr.args:
                    expression(child)
            def clause(item):
                if item.role: roles.add(item.role)
                if item.alias: roles.add(item.alias)
                for expr in item.expressions: expression(expr)
                for block in item.blocks:
                    for child in block: clause(child)
            for item in pattern.clauses: clause(item)
            self._inputs[pattern_key] = tuple(sorted('$'+role for role in roles))
        key = (pattern_key,tuple((role,row.bindings[role]) for role in self._inputs[pattern_key] if role in row.bindings))
        cached = self._matches.get(key)
        if cached is not None:
            self._matches.move_to_end(key)
            outcomes = iter(cached)
        else:
            bindings = {key.removeprefix('$'): self.view.nodes.get(value, value)
                        for key, value in row.bindings.items()}
            outcomes = self.engine.match(pattern, bindings)
        collected = []
        for values, uncertain in outcomes:
            self.executor.tick()
            if cached is None and len(collected) <= 16:
                collected.append(({role:values[role] for role in pattern.outputs},uncertain))
            result = dict(row.bindings)
            reasons = set(row.unknown)
            if uncertain:
                reasons.add('source_body:unknown')
            for role in pattern.outputs:
                value = values[role]
                if isinstance(value, (Node, OperationValue)):
                    result['$'+role] = value.local_id
                elif is_unknown(value):
                    result['$'+role] = '@unknown:'+role
                    reasons.add('source_body:unknown')
                else:
                    result['$'+role] = str(value)
            owner = self.view.nodes.get(row.bindings['$'+pattern.owner])
            yield Row(result, row.evidence + [{'body_owner': getattr(owner, 'local_id', None)}], reasons)
        if cached is None and len(collected) <= 16:
            self._matches[key] = tuple(collected)
            while len(self._matches) > 1024:
                self._matches.popitem(last=False)
