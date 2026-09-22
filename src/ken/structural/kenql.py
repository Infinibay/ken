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


from .relational import RELATIONS, Node, Query, Row, merge_proofs, Executor as Engine


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
            invalid.discard('execution')
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
    # Compatibility entry point for clients that loaded saved rules before KQL 2.
    # KQL 2 has its own lexer/compiler and never enters Parser below.
    if source.lstrip().startswith('language "kql/2"'):
        from ken.kql2.catalog import compile_source
        return compile_source(source)
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


from .query_view import query_graph
