"""KenQL blocks and hygienic named-query composition over indexed fact relations.

This module is independent of language frontends and catalog metadata. Missing
semantic coverage is never interpreted as proof of an absent relationship.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

from .model import Entity, Fact, FactIndex, IR
from .query import Clause, Pattern, QueryBudget, QuotedTerm, _compare, _Exhausted, _bind, _resolve, _variable

TOKEN = re.compile(r'\s*(?:(\#[^\n]*)|("(?:\\.|[^"\\])*")|(/(?:\\.|[^/\\\n])*/[ims]*)|(\$[\w]+(?:\.[\w]+)?)|([A-Za-z_][\w.-]*)|(>=|<=|==|!=|[0-9]+)|([{}():,;\[\]*=<>]))')


RELATIONS = frozenset('HAS_INITIALIZER FIELD_NAME INITIALIZES_FIELD ITERATED_CALL OPTIONAL_VALUE OPTIONAL_OR OPTIONAL_PRESENT OPTIONAL_FALLBACK BODY_VALUE NULL_TEST BRANCH_TRUE BRANCH_FALSE SYNTAX_NODE SYNTAX_PARENT HANDLER_OF ENCLOSING_LOOP IN_HANDLER IN_TRY_BODY CONTINUE_TARGET DERIVE_NAME INVOKES_RESULT_OF CONTAINER CALLEE_VALUE INDEX ITERATES_KEYS_CALLS ADVANCES_ITERATOR MEMBER_OF INSERTS_INTO INSERTED_VALUE LOADED_FROM ACQUIRES ACQUIRES_LOCK ALLOCATES_TYPE ARGUMENT ASSIGN ASSIGNED_FROM AWAIT BASE_NAME BINDS_TO BINDS_TYPE_PARAMETER BRANCH CALL CALLABLE CALLEE_NAME CALLS CAPTURES CFG_NEXT CLASS COLLECTION CONDITIONAL_DELEGATION CONFORMS_TO MATCHES_SIGNATURE CONTEXT_ENTRY CREATES CREATES_CONTEXT CREATES_LOCK DECLARES DECORATED_BY DECORATOR DELEGATES_TO DELEGATES_TYPE ELEMENT_TYPE EMBEDS ENTITY EXPORT EXPORT_SYNTAX EXTENDS FLOWS_TO FUNCTION GUARDS_WRITE HAS_ HAS_ASYNC_SCOPE HAS_CALL HAS_FIELD HAS_HAZARD HAS_METHOD HAS_OPERATION HAS_PARAMETER HAZARD IMPLEMENTS IMPORT IMPORT_SYNTAX INITIALIZED_AS INSTANCE_OF INTERFACE IN_TYPE IS ITERATES_CALLS JOINS LOOKS_UP LOOP MATCH MAY_ MAY_BIND_TO MAY_CALLS MAY_TARGET MAY_TYPE MEMBER MODULE NATIVE NULL OPERATION OVERRIDES OWNED_BY OWNER PARAMETER PASSES_SELF_TO READS RECEIVER RELEASES RELEASES_LOCK RESOURCE_SCOPE RESULT RETURN RETURNS RETURNS_CALL RETURNS_LOOKUP RETURNS_NEW RETURNS_NEW_SELF RETURNS_SELF RETURNS_STORAGE RETURNS_VALUE RETURN_TYPE_ARGUMENT SATISFIES SPAWNS_CONTEXT SPREAD STARTS_CONTEXT STORAGE STORES_VALUE SUBTYPE_OF TARGET THROW TRY TYPE TYPE_NAME TYPE_PARAMETER VALUE VALUE_FLOW VARIADIC WAITS_FOR WRITES WRITES_ELEMENT YIELD _PARSER _PARSER_TS _PARSER_TSX'.split())

RELATIONS |= frozenset({'ASSIGNMENT_TARGET', 'ASSIGNMENT_VALUE', 'RETURN_OPERAND', 'RETURN_ORIGIN', 'RETURN_REACHES', 'RETURN_FLOW_STATUS'})
RELATIONS |= frozenset({'TYPE_HEAD', 'FINAL_MEMBER_INPUT', 'MEMBER_FLOW_STATUS',
                       'FINAL_BINDING_INPUT', 'BINDING_FLOW_STATUS'})
RELATIONS |= frozenset({'TRUTH_TEST', 'INSTANCE_RECEIVER', 'PARAMETER_TEST'})
RELATIONS |= frozenset({'CONSTRUCTOR_INVENTORY', 'RESOLVED_ALLOCATION_COUNT'})
RELATIONS |= frozenset({'FIELD_DECLARATION', 'FIELD_INITIAL_STATUS', 'FIELD_INITIAL_VALUE',
                        'NORMAL_COMPLETION', 'LOOP_BODY_TAIL', 'HANDLER_FALLTHROUGH'})
RELATIONS |= frozenset({'CLASS_EXPRESSION', 'BASE_VALUE', 'TYPE_ASSERTION_VALUE'})
RELATIONS |= frozenset({'BINDING_WRITE_STATUS', 'UNREASSIGNED_BINDING', 'UNIQUE_BINDING_WRITE',
                       'ARGUMENT_ORIGIN', 'ARGUMENT_REACHES'})
RELATIONS |= frozenset({'BINDING_WRITE_COUNT', 'NOMINAL_ROOT', 'NOMINAL_ROOT_STATUS', 'CPP_FIELD_DECL_STATUS', 'TYPE_QUALIFIER', 'TYPE_HEAD_STATUS'})
RELATIONS |= frozenset({'METHOD_SIGNATURE_STATUS', 'VIRTUAL_METHOD', 'INITIALIZER_FORM', 'INITIALIZER_ARGUMENT',
                       'CONSTRUCTOR_INITIALIZER_STATUS', 'CONSTRUCTOR_INITIALIZER_INPUT'})
RELATIONS |= frozenset({'TYPE_REF', 'RETURN_TYPE_REF', 'TYPE_KIND', 'TYPE_NATIVE', 'TYPE_BITS', 'TYPE_SIGNED', 'TYPE_EXTENT', 'TYPE_ARGUMENT'})
RELATIONS |= frozenset({'OPERATOR', 'OPERAND'})
RELATIONS |= frozenset({'TYPE_RANK'})
RELATIONS |= frozenset({'CFG_ENTRY', 'CFG_EXIT', 'CFG_STATUS', 'CONTROL_CONDITION', 'CONTROL_BODY', 'CONTROL_ITERABLE'})
RELATIONS |= frozenset({'EMPTY_COLLECTION', 'CLEARS_COLLECTION', 'AFTER_ITERATION'})
RELATIONS |= frozenset({'ITERATION_SOURCE', 'ITERATION_BODY', 'ITERATION_BINDING'})
RELATIONS |= frozenset({'COLLECTION_SNAPSHOT_OF', 'ITERATION_SNAPSHOT', 'ITERATION_INVOKES_VALUE'})
RELATIONS |= frozenset({'EFFECTIVE_METHOD', 'INSTANCE_SLOT', 'ACCESS_INPUT'})
RELATIONS |= frozenset({'INSERTED_INPUT', 'ITERATION_ORIGIN', 'ITERATION_PASSES_VALUE'})
RELATIONS |= frozenset({'DISCARDS_RESULT', 'INSTANCE_RECEIVER', 'PARAMETER_INITIALIZES_FIELD', 'CONSTRUCTOR_FIELD_INPUT', 'DECLARED_TARGET'})
RELATIONS |= frozenset({'RETURN_FIELD_STATE', 'FIELD_STATE_ORIGIN', 'FIELD_STATE_WRITE'})
RELATIONS |= frozenset({'MEMBER_DECLARATION', 'DECLARES_EVENT', 'ADDS_HANDLER', 'REMOVES_HANDLER', 'RAISES_EVENT'})
RELATIONS |= frozenset({'CONSTRUCTOR_TARGET', 'CONSTRUCTOR_STATUS', 'CALL_BINDING', 'BINDING_STATUS',
                       'BINDING_PARAMETER', 'BINDING_VALUE', 'BINDING_TARGET',
                       'RETURNS_FIELD', 'FINAL_FIELD_INPUT', 'FINAL_FIELD_VALUE', 'FIELD_FLOW_STATUS', 'CALL_RECEIVER_INPUT'})

# Relations a scoped ``not`` may read to decide whether an owner holds a subject,
# and the relations that name global entities and so are never owner-scoped.
_OWNERSHIP_RELATIONS = ('HAS_OPERATION', 'HAS_PARAMETER', 'HAS_CALL', 'HAS_METHOD', 'DECLARES')
_GLOBAL_RELATIONS = frozenset({'ENTITY', 'TYPE', 'INSTANCE_OF'})
# Nodes whose binding, scope or evidence semantics forbid running a later
# constraint ahead of them.
_BARRIERS = frozenset({'any', 'match', 'not', 'count', 'optional', 'path'})

@dataclass
class Node:
    kind: str
    value: Any = None
    children: list[list[Node]] = field(default_factory=list)


@dataclass
class Query:
    name: str
    nodes: list[Node]
    exports: dict[str, str]

    def dependencies(self) -> list[tuple[str, dict[str, str]]]:
        def walk(nodes):
            for n in nodes:
                if n.kind == 'match':
                    yield n.value[0], n.value[1]
                for child in n.children:
                    yield from walk(child)
        return list(walk(self.nodes))


SELECTORS = {'entity': '_', 'type_decl': 'CLASS|INTERFACE', 'class': 'CLASS',
             'interface': 'INTERFACE', 'callable': 'CALLABLE', 'method': 'CALLABLE',
             'function': 'CALLABLE', 'parameter': 'PARAMETER', 'variable': 'STORAGE',
             'value': 'VALUE', 'call': 'CALL', 'module': 'MODULE',
             'closure': 'CALLABLE', 'resource': 'RESOURCE', 'context': 'CONTEXT'}
NESTED = {'has_method': ('HAS_METHOD', 'CALLABLE'), 'has_parameter': ('HAS_PARAMETER', 'PARAMETER'),
          'has_argument': ('ARGUMENT', 'ARGUMENT'), 'has_field': ('HAS_FIELD', 'STORAGE')}


class Parser:
    def __init__(self, source: str):
        self.tokens: list[str] = []
        offset = 0
        while source[offset:].strip():
            m = TOKEN.match(source, offset)
            if m is None:
                line = source.count('\n', 0, offset) + 1
                raise ValueError(f'KenQL line {line}: invalid token near {source[offset:offset+32]!r}')
            if not m[1]:
                self.tokens.append(next(x for x in m.groups()[1:] if x is not None))
            offset = m.end()
        self.i = 0
        self.serial = 0

    def peek(self, token: str) -> bool:
        return self.i < len(self.tokens) and self.tokens[self.i] == token

    def take(self, expected: str | None = None) -> str:
        if self.i == len(self.tokens):
            raise ValueError(f'KenQL: expected {expected or "token"}, reached end')
        token = self.tokens[self.i]
        self.i += 1
        if expected is not None and token != expected:
            raise ValueError(f'KenQL: expected {expected!r}, got {token!r}')
        return token

    def variable(self) -> str:
        result = self.take()
        if not result.startswith('$'):
            raise ValueError(f'expected bound role, got {result}')
        return result

    def term(self) -> str:
        token = self.take()
        return QuotedTerm(token) if token.startswith('"') else token

    def value(self) -> tuple[str, str]:
        t = self.take()
        if t == '[':
            items = []
            while not self.peek(']'):
                op, item = self.value()
                if op != '=':
                    raise ValueError('alternatives require literals')
                items.append(item)
                if not self.peek(']'): self.take(',')
            self.take(']')
            if not items: raise ValueError('empty alternatives')
            return '=', '|'.join(items)
        if t.startswith('"'): return '=', json.loads(t)
        if t.startswith('/'):
            pattern, flags = t[1:].rsplit('/', 1)
            if len(pattern) > 512 or re.search(r'\\[1-9]|\(\?', pattern):
                raise ValueError('KenQL regex must be regular: no backreferences or lookaround')
            from .query import _regex
            pattern = (f'(?{flags})' if flags else '') + pattern
            _regex(pattern)
            return 'regex', pattern
        return '=', t

    def attrs(self, end: str) -> list[tuple[str, str, str]]:
        attrs = []
        while not self.peek(end):
            key = self.take(); self.take(':'); op, value = self.value()
            if value != '*': attrs.append((key, op, value))
            if not self.peek(end): self.take(',')
        self.take(end)
        return attrs

    def block(self) -> list[Node]:
        self.take('{'); result: list[Node] = []
        while not self.peek('}'):
            result.extend(self.statement())
        self.take('}')
        return result

    def statement(self, parent: str = '') -> list[Node]:
        tag = self.take()
        if tag in SELECTORS or tag == 'operation' or tag in NESTED:
            self.take('('); attrs = self.attrs(')')
            if self.peek('as'):
                self.take(); alias = self.variable()
            else:
                self.serial += 1; alias = f'$_local{self.serial}'
            allowed = {'instance_constructor', 'visibility_basis', 'visibility_status', 'explicit_arguments', 'name', 'kind', 'native_kind', 'language', 'type', 'type_family', 'type_state', 'return_type', 'return_family', 'return_type_state', 'position', 'pos', 'receiver', 'parameter_kind', 'declared', 'static', 'async', 'generator', 'visibility', 'owner', 'delegated', 'method', 'mutable', 'storage_kind', 'path', 'path_glob', 'resolution', 'dispatch', 'keyword', 'spread_kind', 'reference_kind', 'native_type', 'native_return_type', 'constructor', 'context_manager', 'arity'}
            invalid = {k for k, _, _ in attrs} - allowed
            if tag == 'operation':
                invalid.discard('role')
            if invalid: raise ValueError(f'unknown selector attributes: {sorted(invalid)}')
            attrs = [('position' if k == 'pos' else k, op, v) for k, op, v in attrs]
            if tag in {'method', 'function'}:
                attrs.append(('method', '=', 'true' if tag == 'method' else 'false'))
            nodes = []
            if tag in NESTED:
                if not parent: raise ValueError(f'{tag} requires an enclosing selector')
                rel, kind = NESTED[tag]
                nodes.append(Node('fact', Clause('require', parent, rel, alias)))
                if tag == 'has_parameter' and not any(k == 'receiver' for k, _, _ in attrs):
                    attrs.append(('receiver', '=', 'false'))
            else:
                if parent: raise ValueError('nested selectors must name a relationship')
                kind = SELECTORS.get(tag, '_')
            nodes.append(Node('fact', Clause('require', alias, 'OPERATION' if tag == 'operation' else 'ENTITY', kind, attrs)))
            if self.peek('{'):
                self.take()
                while not self.peek('}'): nodes.extend(self.statement(alias))
                self.take('}')
            else: self.take(';')
            return nodes
        if tag == 'require':
            a, relation, b = self.term(), self.take(), self.term()
            if not re.fullmatch('[A-Z][A-Z_0-9]*', relation): raise ValueError('invalid relation')
            attrs = []
            if self.peek('['): self.take(); attrs = self.attrs(']')
            self.take(';')
            return [Node('fact', Clause('require', a, relation, b, attrs))]
        if tag == 'match':
            name = self.take()
            if not name.startswith('"'): raise ValueError('match requires a quoted query id')
            name = json.loads(name); self.take('('); bindings = {}
            while not self.peek(')'):
                role = self.take(); self.take(':')
                if role in bindings: raise ValueError(f'duplicate role {role}')
                bindings[role] = self.variable()
                if not self.peek(')'): self.take(',')
            self.take(')'); proof = ''
            if self.peek('as'): self.take(); proof = self.variable()
            self.take(';')
            return [Node('match', (name, bindings, proof))]
        if tag == 'any':
            branches = [self.block()]
            while self.peek('or'): self.take(); branches.append(self.block())
            if len(branches) < 2: raise ValueError('any requires or')
            return [Node('any', children=branches)]
        if tag == 'optional': return [Node('optional', children=[self.block()])]
        if tag == 'not':
            self.take('exists'); child = self.block(); self.take('within')
            scope = self.take(); self.take('('); owner = self.variable(); self.take(')'); self.take(';')
            if scope not in {'callable', 'module'}: raise ValueError('unsupported absence scope')
            return [Node('not', (scope, owner), [child])]
        if tag == 'count':
            self.take('distinct'); role = self.variable(); op = self.take(); count = int(self.take())
            if op not in {'>=', '<=', '=', '>', '<'}: raise ValueError('invalid count comparison')
            child = self.block(); self.take(';')
            return [Node('count', (role, op, count), [child])]
        if tag == 'where':
            a, op, b = self.take(), self.take(), self.take()
            if op not in {'==', '!=', '<', '>', '<=', '>='}: raise ValueError('invalid where comparison')
            self.take(';'); return [Node('where', (a, op, b))]
        if tag == 'different':
            a,b = self.variable(), self.variable(); self.take(';')
            return [Node('different',(a,b))]
        if tag == 'path':
            a,rel=self.term(),self.take(); self.take('{'); lo=int(self.take()); self.take(','); hi=int(self.take()); self.take('}')
            b=self.term(); self.take('as'); proof=self.variable(); self.take(';')
            if not 0 <= lo <= hi <= 32: raise ValueError('path bounds must satisfy 0 <= min <= max <= 32')
            return [Node('path',(a,rel,b,lo,hi,proof))]
        if tag == 'emit':
            exports = {}
            while True:
                role=self.take()
                if role.startswith('$'): name, variable=role[1:],role
                else: name=role; self.take('='); variable=self.variable()
                if name in exports: raise ValueError(f'duplicate export {name}')
                exports[name]=variable
                if not self.peek(','): break
                self.take(',')
            self.take(';'); return [Node('emit',exports)]
        raise ValueError(f'unknown KenQL clause {tag}')


def parse(source: str) -> Query:
    p=Parser(source); p.take('query'); name=p.take(); nodes=p.block()
    if p.i != len(p.tokens): raise ValueError('unexpected tokens after query')
    if not nodes or nodes[-1].kind != 'emit': raise ValueError('query must end with emit')
    exports=nodes.pop().value
    if any(n.kind=='emit' for n in nodes): raise ValueError('emit must be last')
    def validate(items: list[Node], bound: set[str]) -> set[str]:
        bound=set(bound)
        for n in items:
            if n.kind=='fact': bound.update(t for t in (n.value.subject,n.value.object) if t.startswith('$'))
            elif n.kind=='match': bound.update(n.value[1].values())
            elif n.kind=='path': bound.update(t for t in (n.value[0],n.value[2],n.value[5]) if t.startswith('$'))
            elif n.kind=='any': bound.update(set.intersection(*(validate(b,bound) for b in n.children)))
            elif n.kind in {'optional','not','count'}:
                local=validate(n.children[0],bound)
                if n.kind=='count' and n.value[0] not in local: raise ValueError('unbound count role')
                if n.kind=='not' and n.value[1] not in bound: raise ValueError('unbound absence scope')
            elif n.kind=='where':
                operands = {v.split('.')[0] for v in (n.value[0], n.value[2]) if v.startswith('$')}
                if not operands <= bound: raise ValueError('where requires bound roles')
            elif n.kind=='different' and not set(n.value)<=bound: raise ValueError('different requires bound roles')
            else:
                if n.kind=='emit': raise ValueError('nested emit is not allowed')
        return bound
    bound=validate(nodes,set())
    if not set(exports.values())<=bound: raise ValueError('emit requires positively bound roles')
    return Query(name,nodes,exports)


@dataclass
class Row:
    bindings: dict[str,str] = field(default_factory=dict)
    evidence: list[Any] = field(default_factory=list)
    unknown: set[str] = field(default_factory=set)


def merge_proofs(first: Row, second: Row) -> Row:
    """Retain disjunctive proofs for an identical projected binding.

    A proof group's unknown reasons belong to that derivation, not to all
    alternatives. Bound evidence independently from result enumeration.
    """
    alternatives: list[dict[str, Any]] = []
    truncated = False
    for row in (first, second):
        if len(row.evidence) == 1 and 'alternatives' in row.evidence[0]:
            group = row.evidence[0]
            candidates = group['alternatives']
            truncated |= group.get('truncated', False)
        else:
            candidates = [{'evidence': row.evidence, 'unknown': sorted(row.unknown)}]
        for candidate in candidates:
            if candidate not in alternatives:
                alternatives.append(candidate)
    alternatives.sort(key=lambda proof: bool(proof['unknown']))
    truncated |= len(alternatives) > 16
    preferred = second if first.unknown and not second.unknown else first
    return Row(preferred.bindings, [{'alternatives': alternatives[:16], 'truncated': truncated}], preferred.unknown)


class Engine:
    """One invocation owns its budget and dependency cache; no mutable global state."""
    def __init__(self, index: FactIndex, queries: dict[str,Query], budget: QueryBudget | None=None, evidence_mode: str="strict"):
        if evidence_mode not in {"strict", "possible"}: raise ValueError("evidence_mode must be strict or possible")
        self.evidence_mode = evidence_mode
        self.scope: str | None = None
        self.index=index; self.queries=queries; self.budget=budget or QueryBudget()
        self.started=time.monotonic(); self.states=0; self.rows=0
        self.cache: dict[tuple, list[Row]] = {}
        self.dependencies: set[str]=set()
        # A scoped ``not`` re-asks the same question for every candidate row: which
        # subjects does this owner hold? The answer only depends on the owner, so
        # the ownership set is computed once instead of re-reading five relations
        # per fact.
        self._owned: dict[str, set[str]] = {}
        # Selectivity of a clause shape, for join ordering only.
        self._sizes: dict[tuple, int] = {}

    def validate(self, root: Query) -> None:
        visited: dict[str, dict[str, set[str]]] = {}
        relations = RELATIONS | self.index.by_relation.keys() | self.index.ir.relations

        def infer(q: Query, stack: list[str]) -> dict[str, set[str]]:
            kinds: dict[str, set[str]] = {}

            def constrain(role: str, allowed: set[str]) -> None:
                if not role.startswith('$') or not allowed: return
                if role in kinds:
                    allowed = kinds[role] & allowed
                    if not allowed: raise ValueError(f"incompatible role kinds for {role} in {q.name}")
                kinds[role] = allowed

            def walk(nodes: list[Node]) -> None:
                for node in nodes:
                    if node.kind == 'fact':
                        c = node.value
                        if c.relation not in relations:
                            raise ValueError(f"unknown graph relation {c.relation}")
                        if c.relation in {'ENTITY', 'IS'} and not c.object.startswith('$') and c.object != '_':
                            constrain(c.subject, {c.object.literal} if isinstance(c.object, QuotedTerm) else set(c.object.split('|')))
                    elif node.kind == 'path':
                        if node.value[1] not in relations:
                            raise ValueError(f'unknown graph relation {node.value[1]}')
                    elif node.kind == 'match':
                        name, bindings, _ = node.value
                        if name not in self.queries: raise ValueError(f'unknown named query {name}')
                        if name in stack: raise ValueError('query dependency cycle: '+' -> '.join(stack+[name]))
                        child = self.queries[name]
                        if not set(bindings) <= child.exports.keys():
                            raise ValueError(f'{name}: unknown export roles {sorted(set(bindings)-child.exports.keys())}')
                        if name not in visited: visited[name] = infer(child, stack+[name])
                        for public, local in bindings.items(): constrain(local, visited[name].get(public, set()))
                    elif node.kind == 'any':
                        # Alternative shapes may expose a union (class OR generator).
                        outer = dict(kinds)
                        alternatives = []
                        for branch in node.children:
                            kinds.clear(); kinds.update(outer); walk(branch); alternatives.append(dict(kinds))
                        kinds.clear(); kinds.update(outer)
                        for role in set.intersection(*(set(a) for a in alternatives)):
                            kinds[role] = set.union(*(a[role] for a in alternatives))
                    else:
                        for branch in node.children:
                            outer = dict(kinds); walk(branch); kinds.clear(); kinds.update(outer)
            walk(q.nodes)
            return {name:kinds.get(role,set()) for name,role in q.exports.items()}
        infer(root, [])

    def tick(self) -> None:
        self.states+=1
        if self.budget.max_states is not None and self.states>self.budget.max_states: raise _Exhausted('max_states')
        if self.budget.timeout_ms is not None and (time.monotonic()-self.started)*1000>=self.budget.timeout_ms: raise _Exhausted('timeout_ms')

    def owned_subjects(self, scope: str) -> set[str]:
        """Subjects ``scope`` owns, memoized per engine.

        ``scope`` is set only while a scoped ``not`` is evaluated, and that
        happens for very many rows against the same owner. Scanning the five
        ownership relations once per owner instead of once per fact is the
        difference between a linear and a quadratic scope check.
        """
        members = self._owned.get(scope)
        if members is None:
            members = {fact.object for relation in _OWNERSHIP_RELATIONS
                       for fact in self.index.rows(relation, scope)}
            self._owned[scope] = members
        return members

    def candidates(self, clause: Clause, sres: str | None, ores: str | None) -> list[Fact]:
        """The smallest index bucket that still contains every row of a clause.

        An exact attribute filter has its own bucket, so ``call(name: "x")`` no
        longer walks the entity relation to find the one call it names. The
        bucket ignores the endpoints (the caller filters those), so this only
        ever picks a candidate list, never an intersection -- every candidate
        list is a superset of the clause's rows.
        """
        rows = self.index.rows(clause.relation, sres, ores)
        for key, op, value in clause.attrs:
            if op != "=" or not value:
                continue
            # ``=`` accepts alternatives (``name: "get|Get"``), so the bucket is
            # their union. Looking up the literal "get|Get" would find nothing and
            # silently drop every row the clause had.
            bucket = [fact for alternative in value.split("|")
                      for fact in self.index.attr_rows(clause.relation, key, alternative)]
            if len(bucket) < len(rows):
                rows = bucket
        return rows

    def clause_size(self, clause: Clause, bindings: dict[str, str]) -> int:
        """How many rows this clause would yield for one representative row.

        ``len(index.rows(...))`` only counts the relation slice; it ignores a
        clause's kind literals and attribute filters. That rated a generator like
        ``call(name: /encode/)`` -- which matches 171 of ~30k calls -- as if it
        enumerated the whole relation, so the optimizer put it last and the join
        cross-producted millions of rows before the filter removed them.

        A clause is counted exactly, once per (clause, endpoints) shape; the count
        only decides join order, so it never changes which rows a query returns.
        """
        sres = _resolve(clause.subject, bindings)
        ores = _resolve(clause.object, bindings)
        key = (id(clause), sres, ores)
        cached = self._sizes.get(key)
        if cached is not None:
            return cached
        facts = self.index.rows(clause.relation, sres, ores)
        subject_filters = sres is not None or (not _variable(clause.subject) and clause.subject != '_')
        object_filters = ores is not None or (not _variable(clause.object) and clause.object != '_')
        if not clause.attrs and not subject_filters and not object_filters:
            size = len(facts)
        else:
            size = 0
            for fact in self.candidates(clause, sres, ores):
                if sres is not None and fact.subject != sres: continue
                if ores is not None and fact.object != ores: continue
                probe: dict[str, str] = {}
                if subject_filters and sres is None and not _bind(clause.subject, fact.subject, probe): continue
                if object_filters and ores is None and not _bind(clause.object, fact.object, probe): continue
                if not all(_compare(fact.attrs.get(k), op, value) for k, op, value in clause.attrs): continue
                size += 1
        self._sizes[key] = size
        return size

    def facts(self, clause: Clause, row: Row) -> list[Row]:
        result = []
        for fact in self.candidates(clause, _resolve(clause.subject, row.bindings), _resolve(clause.object, row.bindings)):
            self.tick()
            self.rows += 1
            if self.budget.max_rows is not None and self.rows > self.budget.max_rows: raise _Exhausted('max_rows')
            if self.scope and clause.relation not in _GLOBAL_RELATIONS:
                if fact.subject != self.scope and fact.subject not in self.owned_subjects(self.scope):
                    continue
            bindings = dict(row.bindings)
            if not _bind(clause.subject, fact.subject, bindings) or not _bind(clause.object, fact.object, bindings): continue
            if not all(_compare(fact.attrs.get(k), op, value) for k, op, value in clause.attrs): continue
            missing = set(row.unknown)
            if fact.attrs.get('modality') == 'may' and not any(k == 'modality' and v == 'may' for k, _, v in clause.attrs):
                missing.add('possible:' + clause.relation)
            result.append(Row(bindings, row.evidence + [{'subject':fact.subject,'relation':fact.relation,'object':fact.object,'source':fact.evidence}], missing))
        return result

    def closed(self, nodes: list[Node], row: Row, owner: str | None = None) -> bool:
        for node in nodes:
            if node.kind == 'fact':
                clause = node.value
                subject = owner or _resolve(clause.subject, row.bindings)
                if subject is None or f'complete:{subject}:{clause.relation}' not in self.index.ir.capabilities:
                    return False
            elif node.kind == 'match':
                name, bindings, _ = node.value
                child = self.queries[name]
                seed = {child.exports[k]:row.bindings[v] for k,v in bindings.items() if v in row.bindings}
                if not self.closed(child.nodes, Row(seed), owner): return False
            for branch in node.children:
                if not self.closed(branch, row, owner): return False
        return True

    def operand(self, text: str, row: Row) -> Any:
        if text.startswith('$'):
            role, _, attr = text.partition('.')
            entity_id = row.bindings[role]
            if not attr: return entity_id
            entity = self.index.ir.entities.get(entity_id)
            if entity is not None and attr == 'name': return entity.name
            if entity is not None and attr in entity.attrs: return entity.attrs[attr]
            facts = self.index.rows('ENTITY', entity_id)
            return facts[0].attrs.get(attr) if facts else None
        if text.startswith('"'): return json.loads(text)
        return text

    @staticmethod
    def where_ready(node: Node, bound: set[str]) -> bool:
        first, _, second = node.value
        return all(not _variable(term) or term.split('.')[0] in bound for term in (first, second))

    def pool_boundary(self, pending: list[Node], bound: set[str]) -> int:
        """End of the stretch of nodes whose order cannot change a result.

        A fact clause may be evaluated at any point in a conjunction: it only adds
        a binding and filters the rows it cannot satisfy. The exceptions are the
        barriers (negation, aggregates, named queries, path and unions own binding
        and scope semantics) and a ``where`` whose operands are not bound yet --
        crossing that one would let a later fact bind a role the ``where`` would
        otherwise have reported as ``attribute:missing``.

        ``different`` and ready ``where`` constraints are *not* boundaries: they
        are pure row filters, so they can be crossed and applied early. Keeping
        the whole stretch reorderable is what lets a cheap check run before an
        expensive fan-out instead of after it.
        """
        for index, node in enumerate(pending):
            if node.kind in _BARRIERS or (node.kind == 'where' and not self.where_ready(node, bound)):
                return index
        return len(pending)

    def ready_filter(self, pending: list[Node], bound: set[str]) -> int | None:
        """Index of a constraint whose roles are already bound, if any.

        ``different`` and ``where`` remove exactly the rows they would remove at
        the end, so evaluating them as soon as their roles exist cannot change a
        result -- but it stops the join from multiplying rows that are about to
        be discarded. In the ``mediator`` catalogue rule the three ``different``
        clauses used to run after 1.8M rows had been built and then removed every
        one of them.
        """
        for index, node in enumerate(pending):
            if node.kind == 'different':
                first, second = node.value
                if first in bound and second in bound:
                    return index
            elif node.kind == 'where' and self.where_ready(node, bound):
                return index
        return None

    def run_nodes(self,nodes: list[Node],rows: list[Row]) -> list[Row]:
        pending = list(nodes)
        while pending and rows:
            # Every row at this point binds the same roles, so the first row's
            # bindings are the representative ones; only the values differ.
            bound = set(rows[0].bindings)
            boundary = self.pool_boundary(pending, bound)
            chosen = 0
            early = self.ready_filter(pending[:boundary], bound)
            if early is not None:
                chosen = early
            else:
                joins = [index for index in range(boundary) if pending[index].kind == 'fact']
                if joins:
                    chosen = joins[0]
                if len(joins) > 1:
                    bindings = rows[0].bindings
                    best = -1
                    for position in joins:
                        size = self.clause_size(pending[position].value, bindings)
                        if best < 0 or size < best:
                            best, chosen = size, position
            n = pending.pop(chosen)
            following=[]
            for row in rows:
                self.tick()
                if n.kind=='fact': following.extend(self.facts(n.value,row))
                elif n.kind=='where':
                    a,op,b=n.value; left,right=self.operand(a,row),self.operand(b,row)
                    if left is None or right is None:
                        following.append(Row(row.bindings,row.evidence,row.unknown|{'attribute:missing'}))
                    elif _compare(left,'=' if op=='==' else op,str(right)):
                        following.append(row)
                elif n.kind=='different':
                    if row.bindings[n.value[0]]!=row.bindings[n.value[1]]: following.append(row)
                elif n.kind=='any':
                    for branch in n.children: following.extend(self.run_nodes(branch,[row]))
                elif n.kind=='match':
                    name,bindings,proof=n.value; child=self.queries[name]
                    seed={child.exports[k]:row.bindings[v] for k,v in bindings.items() if v in row.bindings}
                    key=(name,self.scope,tuple(sorted(seed.items())))
                    if key not in self.cache: self.cache[key]=self.run_nodes(child.nodes,[Row(seed)])
                    self.dependencies.add(name)
                    matched_rows: dict[tuple, Row] = {}
                    for hit in self.cache[key]:
                        b=dict(row.bindings); accepted=True
                        for role,target in bindings.items():
                            value=hit.bindings[child.exports[role]]
                            if target in b and b[target]!=value: accepted=False; break
                            b[target]=value
                        identity=tuple(sorted(b.items()))
                        if accepted:
                            match_row=Row(b,row.evidence+[{'query':name,'proof':proof,'evidence':hit.evidence}],row.unknown|hit.unknown)
                            old=matched_rows.get(identity)
                            matched_rows[identity] = match_row if old is None else merge_proofs(old, match_row)
                    following.extend(matched_rows.values())
                elif n.kind in {'count','not','optional'}:
                    previous_scope = self.scope
                    if n.kind == 'not': self.scope = row.bindings[n.value[1]]
                    try:
                        hits=self.run_nodes(n.children[0],[row])
                    finally:
                        self.scope = previous_scope
                    if n.kind=='optional':
                        following.append(Row(row.bindings,row.evidence+[{'optional':h.evidence} for h in hits],row.unknown))
                    elif n.kind=='not':
                        certain=[h for h in hits if h.unknown <= row.unknown]
                        if not certain:
                            missing=set(row.unknown)
                            if hits or not self.closed(n.children[0],row,row.bindings[n.value[1]]):
                                missing.add(f'absence:{n.value[0]}:{row.bindings[n.value[1]]}')
                            following.append(Row(row.bindings,row.evidence,missing))
                    else:
                        role,op,num=n.value; count=len({h.bindings[role] for h in hits if h.unknown <= row.unknown})
                        # Lower bounds can be established by witnesses. Exact/upper
                        # counts need relation-scoped closure, never global syntax.
                        if _compare(count,op,str(num)):
                            missing=set(row.unknown)
                            if op in {'=','<=','<'} and not self.closed(n.children[0],row): missing.add('cardinality:open_world')
                            following.append(Row(row.bindings,row.evidence,missing))
                        elif not self.closed(n.children[0],row):
                            following.append(Row(row.bindings,row.evidence,row.unknown|{'cardinality:open_world'}))
                elif n.kind=='path':
                    a,rel,b,lo,hi,proof=n.value
                    resolved_start = _resolve(a, row.bindings)
                    starts=[resolved_start] if resolved_start is not None else sorted(set(self.index.ir.entities) | {f.subject for f in self.index.rows(rel)} | {f.object for f in self.index.rows(rel)})
                    for start in starts:
                        frontier: list[tuple[str,list[str],set[str]]] = [(start,[],set())]; seen_targets: set[tuple[str,bool]]=set()
                        for depth in range(hi+1):
                            nxt=[]
                            # This path operator exposes the first witness for an
                            # endpoint/modality, not every walk. At a given depth,
                            # convergent walks have identical future reachability.
                            # Keep depths separate: a cycle may satisfy a lower
                            # bound that its earlier visit did not satisfy.
                            next_states: set[tuple[str, bool]] = set()
                            for target,witness,path_unknown in frontier:
                                self.tick()
                                if depth>=lo and (target,bool(path_unknown)) not in seen_targets:
                                    seen_targets.add((target,bool(path_unknown)))
                                    if b not in row.bindings or row.bindings[b]==target:
                                        bindings=dict(row.bindings)
                                        if _bind(a,start,bindings) and _bind(b,target,bindings):
                                            bindings[proof]=json.dumps([start]+witness)
                                            following.append(Row(bindings,row.evidence+[{'path':rel,'nodes':[start]+witness}],row.unknown|path_unknown))
                                if depth<hi:
                                    for f in self.index.rows(rel,target):
                                        self.rows+=1
                                        if self.budget.max_rows is not None and self.rows>self.budget.max_rows: raise _Exhausted('max_rows')
                                        uncertainty = path_unknown | ({'possible:'+rel} if f.attrs.get('modality')=='may' else set())
                                        state = (f.object, bool(uncertainty))
                                        if state not in next_states:
                                            next_states.add(state)
                                            nxt.append((f.object,witness+[f.object],uncertainty))
                            frontier=nxt
                else: raise ValueError(f'unsupported node {n.kind}')
            rows=following
        return rows

    def execute(self,q: Query) -> dict[str,Any]:
        self.validate(q); complete=True; reasons=[]; results=[]
        try:
            results=self.run_nodes(q.nodes,[Row()])
        except _Exhausted as exc:
            complete=False; reasons.append(f'budget:{exc}')
        matches: list[dict[str,Any]]=[];seen: dict[tuple, tuple[Row, dict[str, Any]]] = {}
        results.sort(key=lambda row: (bool(row.unknown), tuple(sorted(row.bindings.items()))))
        for row in results:
            if row.unknown and self.evidence_mode == 'strict':
                reasons.extend(sorted(row.unknown))
                continue
            binding={f'${name}':row.bindings[v] for name,v in q.exports.items()}
            key=tuple(sorted(binding.items()))
            if key in seen:
                previous, match = seen[key]
                merged = merge_proofs(previous, row)
                match['evidence'] = merged.evidence
                seen[key] = merged, match
                continue
            if self.budget.max_matches is not None and len(matches)>=self.budget.max_matches: complete=False; reasons.append('budget:max_matches');break
            matches.append({'bindings':binding,'status':'unknown' if row.unknown else 'structural_match',
                            'unknown':sorted(row.unknown),'evidence':row.evidence,'variant':'default', 'evidence_score':1.0})
            seen[key] = row, matches[-1]
        return {'matches':matches,'complete':complete,'unknown':sorted(set(reasons)),
                'stats':{'states':self.states,'rows_examined':self.rows,'elapsed_ms':round((time.monotonic()-self.started)*1000,3),'dependencies':sorted(self.dependencies)}}


def legacy_query(source: str, name: str = 'query') -> Query:
    """Expose existing graph queries through the same named-relation interface."""
    from .selectors import parse_query
    p=parse_query(source)
    def convert(clauses):
        nodes=[]
        for c in clauses:
            if c.mode=='require': nodes.append(Node('fact',c))
            elif c.mode=='optional': nodes.append(Node('optional',children=[[Node('fact',replace(c,mode='require'))]]))
            elif c.mode=='count': nodes.append(Node('count',(c.distinct or c.object,c.count_op,c.count),[[Node('fact',replace(c,mode='require'))]+convert(c.where)]))
            elif c.mode=='forbid':
                raise ValueError('legacy negation cannot be imported without an explicit scope')
        return nodes
    nodes=convert(p.clauses)
    if p.variants: nodes.append(Node('any',children=[convert(v) for v in p.variants.values()]))
    nodes.extend(Node('different',pair) for pair in p.different)
    def bound(nodes):
        result=set()
        for n in nodes:
            if n.kind=='fact': result.update(t for t in (n.value.subject,n.value.object) if t.startswith('$'))
            elif n.kind=='any': result.update(set.intersection(*(bound(b) for b in n.children)))
        return result
    exports={v[1:]:v for v in bound(nodes)}
    if name in {'factory-method','gof.factory-method'}: exports['creator']='$unit'
    return Query(name,nodes,exports)


def query_graph(ir: IR) -> FactIndex:
    """A non-mutating view with argument occurrences and normalized query metadata.

    Kept separate from legacy facts so previously stored queries retain semantics.
    """
    if ir.view == "query":
        return FactIndex(ir)
    graph=IR(ir.path,ir.language,dict(ir.entities),list(ir.operations),[],set(ir.capabilities),list(ir.diagnostics))
    graph.entities = {key: replace(e, name=e.attrs.get("name", e.name)) if e.kind == "CALL" else e for key,e in graph.entities.items()}
    graph.view = "query"
    graph.relations = set(ir.relations)
    methods={f.object for f in ir.facts if f.relation=='HAS_METHOD'}
    arities: dict[str, set[str]] = {}
    for fact in ir.facts:
        if fact.relation == 'HAS_PARAMETER' and not fact.attrs.get('receiver'):
            arities.setdefault(fact.subject, set()).add(fact.object)
    generators={f.subject for f in ir.facts if f.relation=='HAS_YIELD'}
    def family(value):
        return {'str':'string','string':'string','String':'string','int':'integer','bool':'boolean','boolean':'boolean'}.get(value,value)
    if not ir.diagnostics:
        for entity in ir.entities.values():
            if entity.kind == 'CALLABLE':
                if entity.attrs.get('language') == 'python':
                    graph.capabilities.add(f'complete:{entity.id}:HAS_PARAMETER')
                # Every call form of the eight analysed languages is classified, so
                # a callable's own calls are enumerated, not sampled. This is what
                # lets a query ask for an exact call cardinality or for the absence
                # of a call. ``tests/structural/test_call_cardinality_closure.py``
                # enumerates the call forms per language; if a grammar renames one,
                # that test fails before the claim becomes a lie. Rust macro
                # invocations are not calls and are deliberately not counted.
                graph.capabilities.add(f'complete:{entity.id}:HAS_CALL')
    call_ids = {e.id for e in ir.entities.values() if e.kind == 'CALL'}
    results = {call: call + '/result' for call in call_ids}
    stored: dict[str, list[str]] = {}
    supported_returns = {f.subject for f in ir.facts
                         if f.relation == 'RETURN_FLOW_STATUS' and f.object == 'supported'}
    return_operations = {o.id: o for o in ir.operations if o.kind == 'RETURN'}
    for fact in ir.facts:
        if fact.relation == 'ASSIGNED_FROM':
            stored.setdefault(fact.subject, []).append(fact.object)
    # Per-argument occurrence facts retain exact source value IDs. Callee names
    # cannot identify results: two calls to the same function may return anything.
    argument_origins = {
        (f.subject, f.object, f.attrs.get('position', 0)): f
        for f in ir.facts if f.relation == 'ARGUMENT_ORIGIN'
    }

    def as_value(source: str, occurrence: str, evidence: list[str], consumer_call: str | None = None,
                 position: int = 0) -> str:
        if source in results:
            return results[source]
        entity = ir.entities.get(source)
        if entity is None or entity.kind not in {'STORAGE', 'PARAMETER'}:
            return source
        value_id = occurrence + '/loaded-value'
        graph.entities[value_id] = Entity(value_id, 'VALUE', entity.name, entity.path, entity.line, entity.end_line,
                                          {'origin': 'load', 'storage': source})
        graph.add(value_id, 'ENTITY', 'VALUE', *evidence[:1], type=entity.attrs.get('type', 'unknown'))
        graph.add(value_id, 'LOADED_FROM', source, *evidence[:1])
        origin = argument_origins.get((consumer_call, source, position)) if consumer_call is not None else None
        live = set(origin.attrs.get('origins', ())) if origin is not None else set()
        for incoming in sorted(set(stored.get(source, ())) | live):
            if incoming not in results:
                continue
            is_must = (origin is not None and origin.attrs.get('modality') == 'must'
                       and incoming in live)
            graph.add(results[incoming], 'VALUE_FLOW', value_id, *evidence[:1],
                      modality='must' if is_must else 'may')
        return value_id

    for call, value_id in results.items():
        entity = ir.entities[call]
        graph.entities[value_id] = Entity(value_id, 'VALUE', '', entity.path, entity.line, entity.end_line, {'origin': call})
        graph.add(value_id, 'ENTITY', 'VALUE')
        graph.add(call, 'RESULT', value_id)
    for f in ir.facts:
        if f.relation=='ARGUMENT':
            aid=f'{f.subject}/argument/{f.attrs.get("position",0)}'
            graph.add(f.subject,'ARGUMENT',aid,*f.evidence[:1])
            graph.add(aid,'VALUE',as_value(f.object,aid,f.evidence,consumer_call=f.subject,position=f.attrs.get("position",0)),*f.evidence[:1])
            source_entity=ir.entities.get(f.object)
            source_attrs=source_entity.attrs if source_entity else {}
            argument_attrs={**f.attrs, 'type':source_attrs.get('type','unknown'), 'type_family':family(source_attrs.get('type','unknown')), 'type_state':'known' if source_attrs.get('native_type') or source_attrs.get('type','unknown')!='unknown' else 'unknown'}
            graph.add(aid,'ENTITY','ARGUMENT',*f.evidence[:1],**argument_attrs)
            continue
        if f.relation=='ENTITY':
            attrs=dict(f.attrs)
            attrs.update(type_family=family(attrs.get('type','unknown')),
                         type_state='known' if attrs.get('native_type') or attrs.get('type','unknown')!='unknown' else 'unknown',
                         return_family=family(attrs.get('return_type','unknown')),
                         return_type_state='known' if attrs.get('native_return_type') or attrs.get('return_type','unknown')!='unknown' else 'unknown',
                         position=attrs.get('pos',attrs.get('position')), kind=attrs.get('parameter_kind',f.object.lower()),
                         method=f.subject in methods, generator=attrs.get('generator',False) or f.subject in generators)
            attrs['async'] = attrs.get('async_',False)
            attrs['arity'] = len(arities.get(f.subject, set())) if not ir.diagnostics else None
            selected_entity = ir.entities.get(f.subject)
            if selected_entity:
                attrs["path"] = selected_entity.path
                if selected_entity.kind == "CALL": attrs["name"] = selected_entity.attrs.get("name", selected_entity.name)
            graph.facts.append(replace(f,attrs=attrs))
        elif f.relation=='OPERATION':
            kind=str(f.attrs.get('kind',f.object)).lower()
            if kind=='yield' and f.attrs.get('delegated'): kind='yield_delegate'
            if kind=='yield' and 'break' in f.attrs.get('tokens',[]): kind='generator_stop'
            graph.facts.append(replace(f,attrs={**f.attrs,'kind':kind}))
        else: graph.facts.append(f)
        if f.relation == 'ALLOCATES_TYPE':
            graph.add(results.get(f.subject, f.subject), 'INSTANCE_OF', f.object, *f.evidence[:1])
        elif f.relation in {'RETURNS', 'ASSIGNED_FROM'}:
            if f.relation != 'RETURNS' or f.subject not in supported_returns:
                value = as_value(f.object, f.subject + '/' + f.relation + '/' + f.object, f.evidence)
                graph.add(f.subject, 'RETURNS_VALUE' if f.relation == 'RETURNS' else 'STORES_VALUE',
                          value, *f.evidence[:1], **({'basis': 'syntax'} if f.relation == 'RETURNS' else {}))
        elif f.relation == 'FLOWS_TO' and f.subject in results and f.object in results:
            graph.add(results[f.subject], 'VALUE_FLOW', results[f.object], *f.evidence[:1], modality='may')
    # A supported return captures its operand's current origin, rather than all
    # assignments to that binding. Keep the source RETURNS facts unchanged.
    for fact in ir.facts:
        if fact.relation != 'RETURN_ORIGIN':
            continue
        operation = return_operations.get(fact.subject)
        if operation is None or operation.owner not in supported_returns:
            continue
        value = as_value(fact.object, fact.subject + '/return-origin/' + fact.object, fact.evidence)
        graph.add(operation.owner, 'RETURNS_VALUE', value, *fact.evidence[:1],
                  **{**fact.attrs, 'basis': 'flow', 'return_operation': operation.id})
    return FactIndex(graph)
