"""KQL 2 graph constraints compiled directly to the shared relational operator IR.

The syntax AST is immutable and persisted by the compilation codec. Lowering
does not print/reparse KenQL, execute source code, or distribute alternatives.
"""
from __future__ import annotations

from hashlib import sha256
from dataclasses import dataclass
from types import MappingProxyType
import json
import re
from typing import TYPE_CHECKING, NoReturn, Any, Mapping

from ken.structural.query import Clause as Edge, QuotedTerm, _regex
from ken.structural.relational import Node, Query, RELATIONS
from .semantic import (RELATIONS as SEMANTIC_RELATIONS, RETURN_OPERAND_HOPS, STATEMENT_ATTRS,
                       STATEMENT_RELATIONS, STATEMENT_UNARY, UNARY_RELATIONS)
from .syntax import Clause, Declaration, Expr, File, SourceExpr

# ``possible_call`` and ``returns_new`` describe possible targets in the model, so
# they require evidence the source can reach them. Dead code publishes the same
# relation with ``execution: unreachable`` and must not satisfy the predicate.
SEMANTIC_ATTRS: dict[str, tuple[tuple[str, str, str], ...]] = {
    'possible_call': (('execution', 'literal', 'possible'),),
    'returns_new': (('execution', 'literal', 'possible'),),
    'returns_self': (('execution', 'literal', 'possible'),),
    'returns_type': (('execution', 'literal', 'possible'),),
    'reads': (('execution', 'literal', 'possible'),),
    'writes': (('execution', 'literal', 'possible'),),
    'writes_element': (('execution', 'literal', 'possible'),),
    'iterates_calls': (('execution', 'literal', 'possible'),),
    'delegates_to': (('execution', 'literal', 'possible'),),
    'guarded_write': (('execution', 'literal', 'possible'),),
    'forwards_slot': (('execution', 'literal', 'possible'),),
}

if TYPE_CHECKING:
    from .compiler import Program


@dataclass(frozen=True, slots=True)
class FrozenEdge:
    mode: str
    subject: str
    relation: str
    object: str
    attrs: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True, slots=True)
class FrozenNode:
    kind: str
    value: Any
    children: tuple[tuple[FrozenNode, ...], ...]


@dataclass(frozen=True, slots=True)
class FrozenQuery:
    name: str
    nodes: tuple[FrozenNode, ...]
    exports: Mapping[str, str]
    definitions: Mapping[str, FrozenQuery]

    def dependencies(self):
        def walk(nodes):
            for node in nodes:
                if node.kind == 'match':
                    yield node.value[0], node.value[1]
                for branch in node.children:
                    yield from walk(branch)
        return list(walk(self.nodes))


def freeze(plan: Query) -> FrozenQuery:
    """Share only immutable operator plans across requests; never mutable rows."""
    def value(item):
        if isinstance(item, Edge):
            return FrozenEdge(item.mode,item.subject,item.relation,item.object,tuple(item.attrs))
        if isinstance(item, Node):
            return FrozenNode(item.kind,value(item.value),value(item.children))
        if isinstance(item, (tuple,list)):
            return tuple(value(v) for v in item)
        if isinstance(item, dict):
            return MappingProxyType({k:value(v) for k,v in item.items()})
        return item
    return FrozenQuery(plan.name,value(plan.nodes),value(plan.exports),
                       MappingProxyType({k:freeze(v) for k,v in plan.definitions.items()}))


def has_graph(tree: File, query: str | None = None) -> bool:
    definitions = {d.name: d for d in tree.declarations}
    seen: set[str] = set()
    def visit(clauses: tuple[Clause, ...]) -> bool:
        for c in clauses:
            if c.kind == 'source_usages': return True
            if c.kind == 'source_require': return True
            if c.kind == 'declaration_initializer' or c.kind == 'initializer' and not c.role or c.kind == 'gap' and 'exit' in c.flags: return True
            if c.kind == 'selector' and c.name in ('macro', 'type_parameter'): return True
            if c.kind in ('edge', 'walk', 'tally', 'count') or any(visit(b) for b in c.blocks):
                return True
            if (c.kind == 'property' and c.name == 'type' and c.expressions
                    and c.expressions[0].kind == 'call' and c.expressions[0].value in ('nominal', 'parameter')):
                # Nominal selectors join declarations across the shared graph.
                # This choice is internal; authored queries stay source syntax.
                return True
            if c.kind == 'property' and c.name in ('reassigned','escapes','initial','writes','effective','exported','target','result_family','captures','discarded','derive','unreplaced','completes'):
                return True
            if c.kind == 'use' and c.name in definitions and c.name not in seen:
                if any(p.direction == 'out' and p.type.name == 'Call' for p in definitions[c.name].parameters):
                    return True  # typed call evidence requires relational source lowering
                seen.add(c.name)
                if visit(definitions[c.name].clauses):
                    return True
        return False
    return any(visit(d.clauses) for d in tree.declarations if d.kind == 'query' and (query is None or d.name == query))


def fail(message: str, node: Clause | Expr | SourceExpr | Declaration | File) -> NoReturn:
    from .compiler import CompileError
    raise CompileError(message, node.span, 'unsupported_capability')


def term(expr: Expr | SourceExpr) -> str:
    if expr.kind == 'role':
        return '$' + expr.value
    if expr.kind == 'wildcard':
        return '_'
    if expr.kind == 'literal':
        if expr.value.startswith('"'):
            return QuotedTerm(expr.value)
        if re.fullmatch(r'-?\d+|true|false|null', expr.value):
            return QuotedTerm(json.dumps(expr.value))
    if expr.kind == 'list' and expr.args:
        values = [term(x) for x in expr.args]
        if all(isinstance(x, QuotedTerm) and '|' not in x.literal for x in values):
            return '|'.join(x.literal for x in values if isinstance(x, QuotedTerm))
    fail('graph endpoint requires a role, literal, wildcard or nonempty literal list', expr)
    raise AssertionError


def matcher(expr: Expr | SourceExpr) -> tuple[str, str]:
    if expr.kind == 'regex':
        pattern, flags = expr.value[1:].rsplit('/', 1)
        if len(pattern) > 512 or re.search(r'\\[1-9]|\(\?', pattern):
            fail('graph regex must be regular (no backreferences or lookaround)', expr)
        pattern = (f'(?{flags})' if flags else '') + pattern
        _regex(pattern)
        return 'regex', pattern
    value = term(expr)
    if isinstance(value, QuotedTerm):
        # Unlike KenQL 1, a string containing | is a literal, not a list.
        return 'literal', value.literal
    if expr.kind == 'list':
        return '=', value
    fail('graph context matcher requires a literal, literal list or regex', expr)
    raise AssertionError


def operand(expr: Expr) -> str:
    if expr.kind == 'role':
        return '$' + expr.value
    if expr.kind == 'member' and len(expr.args) == 2 and expr.args[1].kind == 'role':
        # ``$place.$field``: the member the pattern's declaration role names.
        return '$' + expr.args[0].value + '.$' + expr.args[1].value
    if expr.kind == 'member' and expr.args[0].kind == 'role':
        return '$' + expr.args[0].value + '.' + expr.value
    if expr.kind == 'literal':
        return expr.value
    fail('graph comparison requires a role, entity attribute or literal', expr)
    raise AssertionError


def lower(declarations: tuple[Declaration, ...], selected: str, namespace: str) -> Query:
    """Validate and lower reachable declarations, with hygienic invocation scopes."""
    definitions = {d.name: d for d in declarations}
    if len(definitions) != len(declarations):
        fail('duplicate declaration', declarations[0])
    plans: dict[str, Query] = {}
    visiting: set[str] = set()

    def identifier(name: str) -> str:
        return namespace + ':' + name

    def declaration(name: str) -> Query:
        if name in visiting:
            fail('recursive graph pattern dependency: ' + name, definitions[name])
        if identifier(name) in plans:
            return plans[identifier(name)]
        if name not in definitions or definitions[name].kind not in ('pattern', 'query'):
            fail('unknown graph pattern: ' + name, definitions[selected])
        source = definitions[name]
        if source.generics:
            fail('graph pattern generics require specialization', source)
        roles = [p.role for p in source.parameters]
        from .source_patterns import DOMAINS, selector
        if len(set(roles)) != len(roles) or any(p.type.name not in DOMAINS or p.type.arguments or p.direction not in ('in', 'out') for p in source.parameters):
            fail('relational parameters require unique in/out source-domain roles', source)
        role_types = {p.role: DOMAINS[p.type.name] for p in source.parameters}
        visiting.add(name)
        aliases: dict[str, str] = {}

        def block(clauses: tuple[Clause, ...], bound: set[str], owner: tuple[str, str] | None = None) -> tuple[list[Node], set[str]]:
            bound = set(bound)
            nodes: list[Node] = []
            forthcoming: list[tuple[str, Clause]] = []
            for clause in clauses:
                kind = clause.kind
                if kind == 'selector':
                    previous = role_types.get(clause.role)
                    compatible = (previous == clause.name or {previous,clause.name} == {'operation','macro'} or
                                  previous == 'type' and clause.name in ('class','interface','trait') or
                                  clause.name == 'type' and previous in ('class','interface','trait') or
                                  {previous,clause.name} in ({'callable','method'},{'callable','constructor'}))
                    if previous and not compatible:
                        fail('incompatible source selectors for $' + clause.role, clause)
                    role_types[clause.role] = clause.name
                    lowered, bound = block(selector(clause, owner), bound)
                    nodes.extend(lowered)
                elif kind == 'source_owned':
                    lowered, bound = block(clause.blocks[0], bound, (clause.role, clause.name))
                    nodes.extend(lowered)
                elif kind == 'source_type':
                    # ``writes: exactly($binding, n)`` names a binding whose own
                    # declaration may only appear later in the same block (a ``var``
                    # declared after the callable's filter, as the catalogs spell it),
                    # so the positive-binding check is deferred to the end of the block.
                    if clause.name == 'writes' and clause.expressions[0].args[0].args[0].value not in bound:
                        forthcoming.append((clause.expressions[0].args[0].args[0].value, clause))
                    spec = ('$'+clause.role,clause.name,clause.expressions[0])
                    if clause.name.startswith('escapes:'):
                        spec = ('$'+clause.role,'escapes',clause.expressions[0],'$'+clause.name.split(':',1)[1])
                    nodes.append(Node('source_type',spec))
                elif kind == 'source_effective_field':
                    attrs=[];type_matcher=None;nominal_role=None;declaration_role=None
                    for prop in clause.blocks[0]:
                        value=prop.expressions[0]
                        if prop.name=='declaration':
                            if value.kind!='role':fail('field declaration requires a Field role',prop)
                            if role_types.get(value.value) not in (None,'field'):
                                fail('field declaration requires a Field role',prop)
                            declaration_role='$'+value.value;bound.add(value.value);role_types[value.value]='field'
                        elif prop.name=='type':
                            if value.kind=='call' and value.value=='nominal' and len(value.args)==1 and len(value.args[0].args)==1 and value.args[0].args[0].kind=='role':
                                nominal=value.args[0].args[0].value
                                previous=role_types.get(nominal)
                                if previous and previous not in ('type','class','interface','trait'):
                                    fail('nominal field type requires a TypeDecl role',prop)
                                nominal_role='$'+nominal;bound.add(nominal);role_types[nominal]='type'
                            else:
                                from .source_types import validate_matcher
                                validate_matcher(value);type_matcher=value
                        else:
                            if prop.name=='visibility' and value.kind=='name':
                                value=Expr('literal',value.span,json.dumps(value.value))
                            op,text=matcher(value);attrs.append((prop.name,op,text))
                    nodes.append(Node('source_effective_field',('$'+clause.name,'$'+clause.role,tuple(attrs),type_matcher,nominal_role,declaration_role)))
                    bound.add(clause.role)
                elif kind == 'source_capture':
                    # ``captures: $x`` binds the captured binding as a value, so the
                    # owner's own BODY can name what it captured (``argument $x at any``
                    # states what the captured binding is passed to).
                    role_types[clause.role] = 'value'
                    bound.add(clause.role)
                elif kind == 'source_receiver':
                    nodes.append(Node('source_receiver',('$'+clause.name,'$'+clause.role)))
                    bound.add(clause.role)
                elif kind == 'source_require':
                    from .source_quantifiers import compile_requirement
                    # ``one allocation`` counts a type's resolved allocation sites;
                    # ``one dispatch`` counts the call sites that dispatch a callable's
                    # own operation, so its owner is the callable itself.
                    owners = (('type', 'class', 'interface', 'trait') if clause.name != 'dispatch'
                              else ('callable', 'method', 'function', 'constructor'))
                    complaint = ('quantified constructor owner requires a selected TypeDecl'
                                 if clause.name != 'dispatch'
                                 else 'quantified dispatch owner requires a selected callable')
                    if clause.role not in bound or role_types.get(clause.role) not in owners:
                        fail(complaint, clause)
                    witness = clause.flags[1] if len(clause.flags) > 1 else ''
                    if witness and witness not in bound:
                        fail('named dispatch witness requires an already selected callable', clause)
                    nodes.append(Node('source_quantifier',compile_requirement(clause)))
                elif kind == 'source_usages':
                    from .source_usages import compile_usage
                    if clause.name not in bound or role_types.get(clause.name) != 'value':
                        fail('usages requires an already captured Value',clause)
                    if clause.role == clause.name or role_types.get(clause.role) not in (None,'usage',''):
                        fail('usage capture requires a Usage role',clause)
                    spec = compile_usage(clause,bound)
                    nodes.append(Node('source_usages',spec))
                    bound.add(clause.role)
                    role_types[clause.role]='usage'
                elif kind == 'declaration_initializer':
                    if owner is None or owner[1] not in ('field','var'):
                        fail('declaration initializer requires a field or variable owner',clause)
                    expression = clause.blocks[0][0]
                    if expression.role not in bound:
                        fail('initializer target must be selected before its expression',expression)
                    expected = ('type','class','interface','trait') if expression.kind == 'construct' else ('call',)
                    if role_types.get(expression.role) not in expected:
                        fail('initializer target has an incompatible source domain',expression)
                    if any(expression.blocks):
                        fail('initializer expression constraints are not yet supported',expression)
                    if expression.alias:
                        previous=role_types.get(expression.alias)
                        if previous and previous!='call':fail('initializer evidence has Call domain',expression)
                        role_types[expression.alias]='call'
                        bound.add(expression.alias)
                    nodes.append(Node('source_initializer',('$'+owner[0],expression.kind,'$'+expression.role,
                                                            '$'+expression.alias if expression.alias else '')))
                elif kind == 'body':
                    from .body import compile_body
                    from .syntax import ParseError
                    if owner is None or owner[1] not in ('callable', 'method', 'constructor', 'module_decl'):
                        fail('BODY requires a callable owner', clause)
                    try:
                        body_roles = {r: t for r, t in role_types.items() if r in bound}
                        source_aliases = {a[1:]: b[1:] for a,b in aliases.items()}
                        body = compile_body(clause, source_aliases.get(owner[0],owner[0]), source_aliases, body_roles, expected_types=role_types)
                        role_types.update(body_roles)
                    except ParseError as exc:
                        fail(str(exc), clause)
                    nodes.append(Node('source_body', body))
                    bound.update(body.outputs)
                elif kind in ('edge', 'walk'):
                    if clause.name not in RELATIONS:
                        fail('unknown graph relation ' + clause.name, clause)
                    endpoints = [term(e) for e in clause.expressions]
                    if len(endpoints) != 2:
                        fail('graph relation requires two endpoints', clause)
                    attrs = []
                    properties = {}
                    for prop in clause.blocks[0]:
                        if prop.kind != 'property' or prop.name in properties:
                            fail('expected unique graph context property', prop)
                        properties[prop.name] = prop.expressions[0]
                    if kind == 'edge':
                        if clause.alias:
                            fail('edge evidence aliases are not supported', clause)
                        attrs = [(key, *matcher(value)) for key, value in properties.items()]
                        nodes.append(Node('fact', Edge('require', endpoints[0], clause.name, endpoints[1], attrs)))
                    else:
                        if set(properties) != {'min', 'max'} or not clause.alias:
                            fail('walk requires min/max and a witness alias', clause)
                        values = [properties[key] for key in ('min', 'max')]
                        if any(v.kind != 'literal' or not v.value.isdecimal() for v in values):
                            fail('walk bounds require integer literals', clause)
                        lo, hi = (int(v.value) for v in values)
                        if not 0 <= lo <= hi <= 32:
                            fail('walk bounds must satisfy 0 <= min <= max <= 32', clause)
                        if clause.alias in bound:
                            fail('walk witness requires a fresh role', clause)
                        nodes.append(Node('path', (endpoints[0], clause.name, endpoints[1], lo, hi, '$' + clause.alias)))
                        bound.add(clause.alias)
                    bound.update(e.value for e in clause.expressions if e.kind == 'role')
                elif kind == 'use':
                    child = declaration(clause.name)
                    params = definitions[clause.name].parameters
                    if definitions[clause.name].kind != 'pattern' or clause.flags:
                        fail('use requires a graph pattern', clause)
                    bindings = {}
                    for arg in clause.expressions:
                        if arg.kind != 'argument' or not arg.value or len(arg.args) != 1 or arg.args[0].kind != 'role' or arg.value in bindings:
                            fail('use requires unique named role arguments', clause)
                        bindings[arg.value] = '$' + arg.args[0].value
                    if not set(bindings) <= child.exports.keys():
                        fail('unknown pattern parameter', clause)
                    if any(p.direction == 'in' and (p.role not in bindings or bindings[p.role][1:] not in bound) for p in params):
                        fail('pattern input must already be bound', clause)
                    for param in params:
                        if param.role in bindings:
                            local=bindings[param.role][1:]
                            expected=DOMAINS[param.type.name]
                            if not role_types.get(local):role_types[local]=expected
                    nodes.append(Node('match', (identifier(clause.name), bindings, '$' + clause.alias if clause.alias else '')))
                    bound.update(v[1:] for v in bindings.values())
                    if clause.alias:
                        if clause.alias in bound:
                            fail('pattern evidence alias requires a fresh role', clause)
                        bound.add(clause.alias)
                elif kind == 'either':
                    outer_types = dict(role_types)
                    branches, branch_types = [], []
                    for alternative in clause.blocks:
                        role_types.clear(); role_types.update(outer_types)
                        branches.append(block(alternative, bound, owner))
                        branch_types.append(dict(role_types))
                    role_types.clear(); role_types.update(outer_types)
                    if len(branches) < 2:
                        fail('either requires at least two alternatives', clause)
                    nodes.append(Node('any', children=[b[0] for b in branches]))
                    common = set.intersection(*(b[1] for b in branches))
                    for role in common:
                        kinds = {types.get(role,'') for types in branch_types}
                        if len(kinds) == 1:
                            role_types[role] = kinds.pop()
                        elif kinds <= {'type','class','interface','trait'}:
                            role_types[role] = 'type'
                        elif kinds <= {'callable','method','constructor'}:
                            role_types[role] = 'callable'
                        elif kinds <= {'field','var','param','receiver','value'}:
                            # A place role: the alternatives agree that the role is
                            # storage (a parameter, a local or a field) even though they
                            # disagree on which. Patterns correlate places by identity --
                            # a director drives the instance it was handed or built --
                            # so the unified role stays usable as a storage role.
                            role_types[role] = 'var'
                        else:
                            role_types[role] = ''
                    bound.update(common)
                elif kind in ('not', 'optional'):
                    from .scopes import private_witnesses

                    if kind == 'not' and owner is None:
                        fail('Place not exists inside a source selector (for example, callable $owner { not exists { call $site {} } }) to define its absence scope', clause)
                    outer_types = dict(role_types)
                    child_nodes, _ = block(private_witnesses(clause.blocks[0], bound, clause.span.start), bound, owner)
                    role_types.clear(); role_types.update(outer_types)
                    # Witnesses are private: the runtime retains the incoming
                    # bindings, including when the inner plan finds nothing.
                    scope = (owner[1], '$' + owner[0]) if owner else None
                    nodes.append(Node(kind, scope, [child_nodes]))
                elif kind in ('tally', 'count'):
                    outer_types = dict(role_types)
                    child_nodes, local = block(clause.blocks[0], bound, owner)
                    role_types.clear(); role_types.update(outer_types)
                    if clause.role not in local:
                        fail('tally requires a positively bound witness', clause)
                    nodes.append(Node('count', ('$' + clause.role, '=' if clause.name == '==' else clause.name, int(clause.flags[0])), [child_nodes]))
                elif kind == 'bind':
                    value = clause.expressions[0]
                    if clauses is not source.clauses or value.kind != 'role' or value.value not in bound or clause.role in bound:
                        fail('graph bind requires a fresh top-level alias of a bound role', clause)
                    aliases['$' + clause.role] = aliases.get('$' + value.value, '$' + value.value)
                    if value.value in role_types:
                        role_types[clause.role] = role_types[value.value]
                    bound.add(clause.role)
                elif kind == 'where':
                    expr = clause.expressions[0]
                    if not isinstance(expr, Expr):
                        fail('graph where requires a query expression', expr)
                    def comparison(expr: Expr) -> None:
                        if expr.kind == 'binary' and expr.value == 'and':
                            for e in expr.args:
                                comparison(e)
                            return
                        if expr.kind == 'call' and expr.value in UNARY_RELATIONS:
                            relation, expected = UNARY_RELATIONS[expr.value]
                            arguments = expr.args
                            if (len(arguments) != 1 or arguments[0].kind != 'argument'
                                    or arguments[0].value or len(arguments[0].args) != 1
                                    or arguments[0].args[0].kind != 'role'):
                                fail('unary semantic relation requires one role', expr)
                            endpoint = operand(arguments[0].args[0])
                            if endpoint[1:].split('.')[0] not in bound:
                                fail('where requires positively bound roles', expr)
                            nodes.append(Node('fact', Edge('require', endpoint, relation,
                                                           QuotedTerm('"' + expected + '"'), [])))
                            return
                        if expr.kind == 'call' and expr.value in SEMANTIC_RELATIONS:
                            relation = SEMANTIC_RELATIONS[expr.value][0]
                            arguments = expr.args
                            def names_an_operand(a) -> bool:
                                # A relation operand names a role, or the member a bound
                                # place offers: ``final_field_value($write, $memento.saved)``.
                                return (a.kind == 'argument' and not a.value and len(a.args) == 1
                                        and (a.args[0].kind == 'role'
                                             or a.args[0].kind == 'member' and a.args[0].args
                                             and a.args[0].args[0].kind == 'role'))
                            if len(arguments) != 2 or any(not names_an_operand(a) for a in arguments):
                                fail('semantic relation requires two named source roles', expr)
                            endpoints = [operand(a.args[0]) for a in arguments]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            attrs = list(SEMANTIC_ATTRS.get(expr.value, ()))
                            nodes.append(Node('fact', Edge('require', endpoints[0], relation, endpoints[1], attrs)))
                            return
                        if expr.kind == 'call' and expr.value == 'initialized_with':
                            # ``initialized_with($storage, $value)``: the value the
                            # storage's declaration initializer is *entered with* -- the
                            # callback a lazy cell is built from. The creation call and the
                            # argument occurrence it carries are fresh witnesses, joined by
                            # the same ARGUMENT/VALUE chain the frontend publishes. An
                            # optional third operand states the creation call's spelling.
                            arguments = expr.args
                            if (len(arguments) not in (2, 3) or any(
                                    a.kind != 'argument' or a.value or len(a.args) != 1
                                    or a.args[0].kind != 'role' for a in arguments[:2])):
                                fail('initialized_with requires two roles and an optional name', expr)
                            endpoints = [operand(a.args[0]) for a in arguments[:2]]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            witnesses: list[str] = []
                            for base in ('initializer_call', 'initializer_argument'):
                                name = base
                                while name in bound or '$' + name in witnesses:
                                    name += '_'
                                witnesses.append('$' + name)
                                bound.add(name)
                            nodes.append(Node('fact', Edge('require', endpoints[0], 'ASSIGNED_FROM',
                                                           witnesses[0], [])))
                            nodes.append(Node('fact', Edge('require', witnesses[0], 'ARGUMENT',
                                                           witnesses[1], [])))
                            nodes.append(Node('fact', Edge('require', witnesses[1], 'VALUE',
                                                           endpoints[1], [])))
                            if len(arguments) == 3:
                                third = arguments[2]
                                if (third.value != 'name' or len(third.args) != 1
                                        or third.args[0].kind != 'literal'):
                                    fail('initialized_with name requires a string pattern', expr)
                                pattern = json.loads(third.args[0].value)
                                _regex(pattern)
                                nodes.append(Node('fact', Edge('require', witnesses[0], 'ENTITY',
                                                               QuotedTerm('"CALL"'),
                                                               [('name', 'regex', pattern)])))
                            return
                        if expr.kind == 'call' and expr.value == 'receives':
                            # ``receives($parameter, $type)``: a call site hands this
                            # method parameter a value the declaration typed as that type,
                            # or the result of a construction of it. The binding and the
                            # value it carries are fresh witnesses, joined by the
                            # BINDING_PARAMETER/BINDING_VALUE chain the frontend
                            # publishes; the type is read either as the value's own
                            # ``TYPE`` or as the type its construction ``ALLOCATES_TYPE``.
                            arguments = expr.args
                            if (len(arguments) != 2 or any(
                                    a.kind != 'argument' or a.value or len(a.args) != 1
                                    or a.args[0].kind != 'role' for a in arguments)):
                                fail('receives requires two named roles', expr)
                            endpoints = [operand(a.args[0]) for a in arguments]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            binding = 'receives_binding'
                            while binding in bound:
                                binding += '_'
                            bound.add(binding)
                            values = []
                            for base in ('receives_value', 'receives_allocation'):
                                value = base
                                while value in bound or '$' + value in values:
                                    value += '_'
                                values.append('$' + value)
                                bound.add(value)
                            nodes.append(Node('fact', Edge('require', '$' + binding,
                                                           'BINDING_PARAMETER', endpoints[0], [])))
                            branches = []
                            for value, relation in zip(values, ('TYPE', 'ALLOCATES_TYPE')):
                                branches.append([
                                    Node('fact', Edge('require', '$' + binding,
                                                      'BINDING_VALUE', value, [])),
                                    Node('fact', Edge('require', value, relation,
                                                      endpoints[1], []))])
                            nodes.append(Node('any', children=branches))
                            return
                        if expr.kind == 'call' and expr.value == 'instance_slot':
                            # ``instance_slot($local, $shared)``: the class-local instance
                            # slot is a view of the slot the declaring class holds
                            # (``INSTANCE_SLOT``). A registration written in a base class
                            # and a lookup performed on a subclass thereby name the same
                            # storage, without either side enumerating the other's fields.
                            arguments = expr.args
                            if (len(arguments) != 2 or any(
                                    a.kind != 'argument' or a.value or len(a.args) != 1
                                    or a.args[0].kind != 'role' for a in arguments)):
                                fail('instance_slot requires two named roles', expr)
                            endpoints = [operand(a.args[0]) for a in arguments]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            nodes.append(Node('fact', Edge('require', endpoints[0],
                                                           'INSTANCE_SLOT', endpoints[1], [])))
                            return
                        if expr.kind == 'call' and expr.value == 'preserves':
                            # ``preserves($callable, $place)``: the callable hands back what
                            # it was given. Either its return *is* that place -- an identity
                            # adapter -- or it returns a wrapper the place was loaded into
                            # (``return wrap(handler)``), which the frontend joins as
                            # ARGUMENT/VALUE/LOADED_FROM. Every arm is a return operation of
                            # the callable, so an unrelated return cannot satisfy the claim.
                            arguments = expr.args
                            if (len(arguments) != 2 or any(
                                    a.kind != 'argument' or a.value or len(a.args) != 1
                                    or a.args[0].kind != 'role' for a in arguments)):
                                fail('preserves requires two named roles', expr)
                            endpoints = [operand(a.args[0]) for a in arguments]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            preservation_witnesses: list[list[str]] = []
                            for base in ('preserved_return', 'preserved_wrapper'):
                                group = []
                                for suffix in (('return',) if base == 'preserved_return' else
                                               ('return', 'wrapper', 'argument', 'loaded')):
                                    name = base + '_' + suffix
                                    while name in bound:
                                        name += '_'
                                    bound.add(name)
                                    group.append('$' + name)
                                preservation_witnesses.append(group)
                            identity, wrapped = preservation_witnesses
                            execution = [('execution', 'literal', 'possible')]
                            branches = [[
                                Node('fact', Edge('require', endpoints[0], 'HAS_OPERATION',
                                                  identity[0], execution)),
                                Node('fact', Edge('require', identity[0], 'RETURN_ORIGIN',
                                                  endpoints[1], [])),
                            ], [
                                Node('fact', Edge('require', endpoints[0], 'HAS_OPERATION',
                                                  wrapped[0], execution)),
                                Node('fact', Edge('require', wrapped[0], 'RETURN_ORIGIN',
                                                  wrapped[1], [])),
                                Node('fact', Edge('require', wrapped[1], 'ARGUMENT',
                                                  wrapped[2], [])),
                                Node('fact', Edge('require', wrapped[2], 'VALUE',
                                                  wrapped[3], [])),
                                Node('fact', Edge('require', wrapped[3], 'LOADED_FROM',
                                                  endpoints[1], [])),
                            ]]
                            nodes.append(Node('any', children=branches))
                            return
                        if expr.kind == 'call' and expr.value in STATEMENT_UNARY:
                            relation, expected = STATEMENT_UNARY[expr.value]
                            arguments = expr.args
                            if (len(arguments) != 1 or arguments[0].kind != 'argument'
                                    or arguments[0].value or len(arguments[0].args) != 1
                                    or arguments[0].args[0].kind != 'role'):
                                fail('statement relation requires one named role', expr)
                            endpoint = operand(arguments[0].args[0])
                            if endpoint[1:].split('.')[0] not in bound:
                                fail('where requires positively bound roles', expr)
                            nodes.append(Node('fact', Edge('require', endpoint, relation,
                                                           QuotedTerm('"' + expected + '"'), [])))
                            return
                        if expr.kind == 'call' and expr.value in STATEMENT_RELATIONS:
                            relation = STATEMENT_RELATIONS[expr.value]
                            arguments = expr.args
                            if (len(arguments) != 2 or any(
                                    a.kind != 'argument' or a.value or len(a.args) != 1
                                    or a.args[0].kind != 'role' for a in arguments)):
                                fail('statement relation requires two named roles', expr)
                            endpoints = [operand(a.args[0]) for a in arguments]
                            if any(v[1:].split('.')[0] not in bound for v in endpoints):
                                fail('where requires positively bound roles', expr)
                            if expr.value == 'returns_operand':
                                # The call sits inside the statement that hands it back,
                                # reached through the syntax chain rather than a single
                                # relation: the return may wrap it.
                                lo, hi = 1, RETURN_OPERAND_HOPS
                                witness = 'returned_operand'
                                if witness in bound:
                                    fail('statement relation witness requires a fresh role', expr)
                                nodes.append(Node('path', (endpoints[1], relation, endpoints[0],
                                                           lo, hi, '$' + witness)))
                                bound.add(witness)
                                return
                            attrs = list(STATEMENT_ATTRS.get(expr.value, ()))
                            nodes.append(Node('fact', Edge('require', endpoints[0], relation,
                                                           endpoints[1], attrs)))
                            return
                        if expr.kind != 'binary' or expr.value not in ('==', '!=', '<', '<=', '>', '>='):
                            fail('graph where currently requires comparisons joined by and', expr)
                        a, b = [operand(e) for e in expr.args]
                        if any(v[1:].split('.')[0] not in bound for v in (a,b) if v.startswith('$')):
                            fail('where requires positively bound roles', expr)
                        if expr.value == '!=' and all(e.kind == 'role' for e in expr.args):
                            nodes.append(Node('different', (a, b)))
                        else:
                            nodes.append(Node('where', (a, {'==':'literal','!=':'not_literal'}.get(expr.value, expr.value), b)))
                    comparison(expr)
                elif kind == 'select':
                    pass
                elif kind in ('order', 'limit'):
                    fail(f'{kind} is unavailable with resolved/graph relationships; use max_rows to bound returned rows (without ordering)', clause)
                else:
                    fail(f'{kind} cannot yet be combined with resolved/graph relationships; isolate that clause in a source-only query and validate both queries against the same fixture', clause)
            for role, clause in forthcoming:
                if role not in bound:
                    fail('writes matcher requires an already bound source binding', clause)
            return nodes, bound

        nodes, bound = block(source.clauses, {p.role for p in source.parameters if p.direction == 'in'})
        exports = {p.role: '$' + p.role for p in source.parameters}
        selects = [c for c in source.clauses if c.kind == 'select']
        if source.kind == 'query':
            if len(selects) != 1:
                fail('graph query requires one select', source)
            exports = {}
            for expr in selects[0].expressions:
                if expr.kind != 'projection' or expr.args[0].kind != 'role':
                    fail('graph select requires roles (optionally as column)', expr)
                role = expr.args[0].value
                public = expr.value or role
                if public in exports:
                    fail('duplicate projection name', expr)
                exports[public] = '$' + role
        elif selects:
            fail('pattern cannot contain select', source)
        if any(v[1:] not in bound for v in exports.values()):
            fail('graph output is not bound in every alternative', source)
        def rewrite(value):
            if isinstance(value, str) and not isinstance(value, QuotedTerm):
                head, dot, tail = value.partition('.')
                return aliases.get(head, head) + dot + tail
            if isinstance(value, Edge):
                return Edge(value.mode, rewrite(value.subject), value.relation, rewrite(value.object), value.attrs)
            if isinstance(value, Node):
                return Node(value.kind, rewrite(value.value), rewrite(value.children))
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, tuple):
                return tuple(rewrite(v) for v in value)
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            return value
        plan = Query(source.name, rewrite(nodes) if aliases else nodes, rewrite(exports) if aliases else exports)
        plans[identifier(name)] = plan
        visiting.remove(name)
        return plan

    result = declaration(selected)
    # A query that only projects a pattern is an interface, not an extra join.
    # Besides avoiding work, inlining preserves uncertain alternative proofs
    # until the outermost strict/possible evidence decision.
    if len(result.nodes) == 1 and result.nodes[0].kind == 'match':
        target, bindings, proof = result.nodes[0].value
        reverse = {v:k for k,v in bindings.items()}
        if not proof and len(reverse) == len(bindings) and all(v in reverse for v in result.exports.values()):
            child = plans[target]
            result = Query(result.name, child.nodes, {k:child.exports[reverse[v]] for k,v in result.exports.items()})
    result.definitions = {key: value for key, value in plans.items() if value is not result}
    return result


def compile_graph(tree: File, query: str | None) -> Program:
    from .compiler import Program
    queries = [d for d in tree.declarations if d.kind == 'query' and (query is None or d.name == query)]
    if len(queries) != 1:
        fail('choose exactly one query', tree)
    chosen = queries[0]
    fingerprint = sha256(repr(tree).encode()).hexdigest()
    lower(tree.declarations, chosen.name, fingerprint)
    from dataclasses import replace
    projection = tuple(replace(e, value=e.value or e.args[0].value) for c in chosen.clauses if c.kind == 'select' for e in c.expressions if isinstance(e, Expr))
    return Program(chosen.name, (), (), projection, (), None, fingerprint, graph=tree.declarations)


def relational_plan(program: Program) -> Query:
    return lower(program.graph, program.name, program.fingerprint)
