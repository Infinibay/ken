"""Capability-checked structural subset. Unsupported constructs fail before I/O."""
from __future__ import annotations

from dataclasses import dataclass, replace, fields, is_dataclass
from hashlib import sha256
import math
from typing import NoReturn, Mapping

from .syntax import Clause, Declaration, Expr, File, ParseError, SourceExpr
from .logic import Predicate, components
from .syntax.ast import Parameter, TypeName
from .semantic import (RELATIONS, STATEMENT_RELATIONS, STATEMENT_UNARY, UNARY_RELATIONS)
from .source_types import validate_matcher
from .body import BodyPattern, compile_body
from .syntax_schema import SYNTAX_PROPERTIES, property_hint

KINDS = {'class': ('CLASS',), 'interface': ('INTERFACE',), 'trait': ('TRAIT',),
         'type': ('CLASS', 'INTERFACE', 'TRAIT', 'STRUCT'), 'module_decl': ('MODULE',),
         'callable': ('CALLABLE',), 'method': ('CALLABLE',), 'function': ('CALLABLE',),
         'constructor': ('CALLABLE',), 'field': ('FIELD',), 'param': ('PARAMETER',),
         'receiver': ('PARAMETER',), 'var':('STORAGE',), 'value':('VALUE','MEMBER'), 'operation':('OPERATION',), 'macro':('OPERATION',),
         'call': ('CALL',),
         'node':('AST_EXPRESSION','AST_STATEMENT','AST_OTHER'), 'expression':('AST_EXPRESSION',), 'statement':('AST_STATEMENT',)}
TYPES = {'TypeDecl': 'type', 'Module': 'module_decl', 'Callable': 'callable', 'Field': 'field', 'Parameter': 'param', 'Receiver': 'receiver', 'Binding':'var', 'Value':'value', 'Operation':'operation', 'Call':'call', 'CodeNode':'node','Expression':'expression','Statement':'statement'}
COMMON = {'name': 'String', 'path': 'String', 'language': 'String', 'native_kind': 'String', 'visibility': 'String'}
PROPERTIES = {kind: dict(COMMON) for kind in KINDS}
# A call occurrence is an entity: its ``name`` is the callee spelling and its
# ``execution`` is the reachability of the call site (dead code is not a call).
PROPERTIES['call'].update(line='Int', execution='String', target='SourceType', result_family='SourceType',
                         resolution='String', discarded='Bool', receiver='SourceType', entry='SourceType',
                         unreplaced='Bool')
for kind in ('callable', 'method', 'function', 'constructor'):
    PROPERTIES[kind].update(arity='Int', static='Bool', generator='Bool', constructor='Bool',
                            context_manager='Bool', functional='Bool', **{'async': 'Bool'})
for kind in ('param', 'receiver'):
    PROPERTIES[kind].update(position='Int', native_position='Int', accepts_position='Bool')
# ``reference_kind: "lvalue"`` states the declarator spelling of a parameter that is
# a reference (IR 1.60 records ``lvalue`` for ``const X&`` and ``rvalue`` for ``X&&``),
# which is what separates a C++ copy constructor from a move or by-value one.
for kind in ('param', 'receiver'):
    PROPERTIES[kind].update(reference_kind='String')
PROPERTIES['param'].update(reassigned='Bool')
PROPERTIES['receiver'].update(escapes='Bool')
PROPERTIES['field'].update(initial='SourceType')
# ``derive: "Clone"`` states a language-accredited derivation the type carries, such
# as Rust's ``#[derive(Clone)]``; it lowers to the existing DERIVE_NAME relation.
PROPERTIES['type'].update(derive='String')
# ``base: $place`` names the runtime base a locally created type carries. The graph
# publishes ``BASE_INPUT(type, place)`` when that place is an unreassigned parameter
# of the declaring callable (see ``structural/value_contracts.py``), so the property
# states the derivation the analysis actually proved. A nominal ``extends Foo``
# spelling is a different fact (``EXTENDS``/``SUBTYPE_OF``).
for _type_kind in ('class', 'interface', 'trait', 'type'):
    PROPERTIES[_type_kind].update(base='SourceType')
for _callable_kind in ('callable','method','constructor'):
    PROPERTIES[_callable_kind].update(writes='SourceType',exported='Bool',captures='SourceType',completes='SourceType')
for kind in ('field','param','receiver','var'):
    PROPERTIES[kind].update(type='SourceType',type_status='String')
PROPERTIES['field'].update(static='Bool',effective='Bool',declaration='Field')
# A binding declared inside a callable can carry a storage class (C++/Java
# function-local ``static``), which the IR publishes as ``static`` on the
# STORAGE entity exactly as it does for a field.
PROPERTIES['var'].update(static='Bool')
for kind in ('callable','method','function','constructor'):
    PROPERTIES[kind].update(return_type='SourceType',return_type_status='String')
PROPERTIES['operation'].update(kind='String',line='Int',execution='String')
for kind in ('node','expression','statement'):
    PROPERTIES[kind].update(SYNTAX_PROPERTIES)
    PROPERTIES[kind].update(namespace='String',scope_kind='String')
    PROPERTIES[kind].update(argument_kind='String',argument_name='String',argument_position='Int',source_position='Int')


@dataclass(frozen=True, slots=True)
class Scan:
    role: str
    selector: str
    owner: str | None
    properties: tuple[tuple[str, Expr], ...]


@dataclass(frozen=True, slots=True)
class Action:
    role: str
    expression: Expr


@dataclass(frozen=True, slots=True)
class Program:
    name: str
    scans: tuple[Scan, ...]
    filters: tuple[Expr, ...]
    projection: tuple[Expr, ...]
    ordering: tuple[Expr, ...]
    limit: int | None
    fingerprint: str
    branches: tuple[Program, ...] = ()
    actions: tuple[tuple[str, Expr], ...] = ()
    predicates: tuple[Predicate, ...] = ()
    optional: tuple[Expr, ...] = ()
    enums: tuple[tuple[str, tuple[str, ...]], ...] = ()
    steps: tuple[Scan | Action | BodyPattern, ...] = ()
    graph: tuple[Declaration, ...] = ()


class CompileError(ParseError):
    pass


def _compile(tree: File, query: str | None = None) -> Program:
    """Compile the supported structural capability, not the entire syntax AST."""
    declarations = {d.name: d for d in tree.declarations}
    def fail(message: str, node: Clause | Expr | File = tree) -> NoReturn:
        raise CompileError(message, node.span, 'unsupported_capability')
    if len(declarations) != len(tree.declarations):
        fail('duplicate declaration')
    if any(name != 'ken.core' for name in tree.imports):
        fail('external library resolver is not implemented')
    if any(d.kind not in ('query', 'pattern', 'predicate', 'enum') or d.generics for d in tree.declarations):
        fail('model/generic compilation is not implemented')
    enums = {d.name:d.values for d in tree.declarations if d.kind == 'enum'}
    if any(name in TYPES or len(set(values)) != len(values) for name, values in enums.items()):
        fail('duplicate enum value or reserved domain name')
    domains = {**TYPES, **{name:'enum:'+name for name in enums}}
    predicates = tuple(Predicate(d.name, d.parameters, d.formula) for d in tree.declarations
                       if d.kind == 'predicate' and d.formula is not None)
    signatures = {p.name: p for p in predicates}
    for predicate in predicates:
        if len({p.role for p in predicate.parameters}) != len(predicate.parameters):
            fail('duplicate predicate parameter', predicate.formula)
        if any(p.type.name not in domains or p.type.arguments for p in predicate.parameters):
            fail('predicate parameters require finite domains', predicate.formula)
    try:
        components(predicates)
    except ParseError as exc:
        raise CompileError(str(exc), exc.span) from exc
    queries = [d for d in tree.declarations if d.kind == 'query' and (query is None or d.name == query)]
    if len(queries) != 1:
        fail('choose exactly one query')
    selected = queries[0]
    scans: list[Scan] = []
    filters: list[Expr] = []
    actions: list[tuple[str, Expr]] = []
    optional: list[Expr] = []
    steps: list[Scan | Action | BodyPattern] = []
    computed_types: dict[str,str] = {}
    roles: dict[str, str] = {}
    counter = 0

    def expression(expr: Expr, mapping: dict[str, str]) -> Expr:
        if expr.kind == 'role':
            return replace(expr, value=mapping.get(expr.value, expr.value))
        return replace(expr, args=tuple(expression(a, mapping) for a in expr.args),
                       parameters=tuple(replace(p, role=mapping.get(p.role, p.role)) for p in expr.parameters))

    def existential(clauses: tuple[Clause, ...], mapping: dict[str, str], owner: str | None, span) -> Expr:
        """Keep anti-join witnesses local and correlate only existing roles."""
        nonlocal counter
        local = dict(mapping)
        parameters: list[Parameter] = []
        constraints: list[Expr] = []
        selector_types = {'class':'TypeDecl', 'interface':'TypeDecl', 'trait':'TypeDecl', 'type':'TypeDecl',
                          'callable':'Callable', 'method':'Callable', 'constructor':'Callable',
                          'field':'Field', 'param':'Parameter', 'receiver':'Receiver', 'module_decl':'Module',
                          'call':'Call',
                          'node':'CodeNode','expression':'Expression','statement':'Statement'}

        def call(name: str, *args: Expr) -> Expr:
            return Expr('call', span, name, tuple(Expr('argument', span, args=(a,)) for a in args))

        def bind(name: str, domain: str) -> str:
            nonlocal counter
            translated = local.get(name, name)
            if translated in roles or any(p.role == translated for p in parameters):
                return translated
            counter += 1
            translated = f'@exists:{counter}:{name}'
            local[name] = translated
            parameters.append(Parameter(TypeName(domain), translated))
            return translated

        def visit(items: tuple[Clause, ...], parent: str | None) -> None:
            import json
            for item in items:
                if item.kind == 'selector':
                    if item.name not in selector_types or item.alias:
                        fail('unsupported existential selector', item)
                    if item.name == 'method' and parent is None:
                        fail('standalone method classification is not implemented', item)
                    role = bind(item.role, selector_types[item.name])
                    entity = Expr('role', item.span, role)
                    constraints.append(call('kind_is', entity, Expr('literal', item.span, json.dumps(item.name))))
                    if parent:
                        constraints.append(call('owns', Expr('role', item.span, parent), entity))
                    for child in item.blocks[0]:
                        if child.kind == 'property':
                            if child.name not in PROPERTIES[item.name]:
                                fail(f'unsupported existential property {child.name!r}. ' + property_hint(child.name), child)
                            expected = child.expressions[0]
                            if not isinstance(expected, Expr):
                                fail('expected query expression', child)
                            if expected.kind != 'wildcard':
                                prop = Expr('member', child.span, child.name, (entity,))
                                if child.name in ('type','return_type'):
                                    constraints.append(Expr('type_test',child.span,args=(prop,expected)))
                                else:
                                    if child.name.endswith('type_status') and expected.kind == 'name' and expected.value in ('known','unknown'):
                                        expected = Expr('literal',expected.span,json.dumps(expected.value))
                                    constraints.append(Expr('binary', child.span, 'matches' if expected.kind == 'regex' else '==', (prop, expression(expected, local))))
                        else:
                            visit((child,), role)
                elif item.kind == 'from':
                    for parameter in item.parameters:
                        if parameter.type.name not in TYPES or parameter.type.arguments:
                            fail('unsupported existential domain', item)
                        bind(parameter.role, parameter.type.name)
                elif item.kind == 'where':
                    formula = item.expressions[0]
                    assert isinstance(formula, Expr)
                    constraints.append(expression(formula, local))
                elif item.kind in ('fields', 'parameters') and not item.flags:
                    visit(item.blocks[0], parent)
                else:
                    fail(f'{item.kind} in existential block is not implemented', item)
        def declare(items: tuple[Clause, ...]) -> None:
            for item in items:
                if item.kind == 'selector' and item.name in selector_types:
                    bind(item.role, selector_types[item.name])
                    declare(item.blocks[0])
                elif item.kind == 'from':
                    for parameter in item.parameters:
                        if parameter.type.name not in TYPES or parameter.type.arguments:
                            fail('unsupported existential domain', item)
                        bind(parameter.role, parameter.type.name)
                elif item.kind in ('fields', 'parameters'):
                    declare(item.blocks[0])
        declare(clauses)
        visit(clauses, owner)
        formula = Expr('literal', span, 'true')
        for constraint in constraints:
            formula = Expr('binary', span, 'and', (formula, constraint))
        return Expr('quantifier', span, 'exists', (formula,), tuple(parameters))

    def lower(clauses: tuple[Clause, ...], mapping: dict[str, str], owner: str | None = None, stack: tuple[str, ...] = (), expected_types: dict[str,str] | None = None) -> None:
        nonlocal counter
        for clause in clauses:
            if clause.kind in ('select', 'order', 'limit'):
                continue
            if clause.kind == 'selector':
                kind = clause.name
                if kind not in KINDS or clause.alias:
                    fail(f'selector {kind} or selector evidence capture is not implemented', clause)
                role = mapping.get(clause.role, clause.role)
                if role in roles and (roles[role] not in KINDS or not set(KINDS[roles[role]]) & set(KINDS[kind]) or {roles[role],kind} == {'param','receiver'}):
                    fail(f'incompatible selector types for ${role}', clause)
                roles[role] = kind
                if owner and kind in ('node','expression','statement') and roles[owner] not in ('node','expression','statement'):
                    fail('common AST selectors require a common AST parent', clause)
                if kind == 'method' and owner is None or kind == 'function':
                    fail('standalone method/function classification is not implemented', clause)
                if owner and not (roles[owner] in ('node','expression','statement') and kind in ('node','expression','statement') or roles[owner] in ('type','class','interface','trait') and kind in ('field','method','constructor','callable') or roles[owner] in ('callable','method','function','constructor') and kind in ('param','receiver','var','operation','call') or roles[owner] == 'module_decl'):
                    fail('unsupported ownership relation', clause)
                props: list[tuple[str, Expr]] = []
                nested: list[Clause] = []
                for child in clause.blocks[0]:
                    if child.kind == 'property':
                        if child.name not in PROPERTIES[kind]:
                            fail(f'property {child.name!r} is not supported for {kind}. ' + property_hint(child.name), child)
                        value = child.expressions[0]
                        if isinstance(value,Expr) and child.name.endswith('type_status') and value.kind == 'name' and value.value in ('known','unknown'):
                            import json
                            value = Expr('literal',value.span,json.dumps(value.value))
                        if not isinstance(value, Expr) or PROPERTIES[kind][child.name] != 'SourceType' and value.kind not in ('literal','regex','wildcard'):
                            fail('property requires a scalar literal, regex or wildcard in this capability', child)
                        props.append((child.name, value))
                    else:
                        nested.append(child)
                scan = Scan(role, kind, owner, tuple(props))
                scans.append(scan)
                steps.append(scan)
                lower(tuple(nested), mapping, role, stack, expected_types)
            elif clause.kind == 'from':
                for param in clause.parameters:
                    if param.type.arguments or param.type.name not in domains:
                        fail('unsupported finite domain', clause)
                    role = mapping.get(param.role, param.role)
                    kind = domains[param.type.name]
                    if role in roles and (roles[role] != kind and (kind not in KINDS or roles[role] not in KINDS or not set(KINDS[roles[role]]) & set(KINDS[kind])) or {roles.get(role),kind} == {'param','receiver'}):
                        fail('incompatible role types', clause)
                    roles[role] = kind
                    scan = Scan(role, kind, None, ())
                    scans.append(scan)
                    steps.append(scan)
            elif clause.kind == 'where':
                expr = clause.expressions[0]
                assert isinstance(expr, Expr)
                transformed=expression(expr,mapping)
                if free_roles(transformed) - roles.keys():
                    fail('where inputs must already be bound', clause)
                filters.append(transformed)
                actions.append(('',transformed))
                steps.append(Action('',transformed))
            elif clause.kind == 'not':
                condition = Expr('unary', clause.span, 'not',
                                 (existential(clause.blocks[0], mapping, owner, clause.span),))
                filters.append(condition)
                actions.append(('', condition))
                steps.append(Action('',condition))
            elif clause.kind == 'optional':
                optional.append(existential(clause.blocks[0], mapping, owner, clause.span))
            elif clause.kind == 'body':
                if owner is None or roles[owner] not in ('callable','method','function','constructor','module_decl','module'):
                    fail('BODY requires a callable owner',clause)
                try:
                    steps.append(compile_body(clause,owner,mapping,roles,expected_types=expected_types))
                except ParseError as exc:
                    raise CompileError(str(exc),exc.span) from exc
            elif clause.kind == 'bind':
                role=mapping.get(clause.role,clause.role)
                if role in roles:
                    fail('bind requires a fresh role',clause)
                roles[role]='#computed'
                expr=clause.expressions[0]
                assert isinstance(expr,Expr)
                transformed = expression(expr,mapping)
                if free_roles(transformed) - (roles.keys() - {role}):
                    fail('bind inputs must already be bound', clause)
                actions.append((role,transformed))
                steps.append(Action(role,transformed))
            elif clause.kind == 'use':
                target = declarations.get(clause.name)
                if target is None or target.kind != 'pattern' or clause.flags or clause.alias:
                    fail('unknown pattern or unsupported model/evidence argument', clause)
                if clause.name in stack:
                    fail('recursive pattern expansion is not supported', clause)
                arguments: dict[str, str] = {}
                for arg in clause.expressions:
                    assert isinstance(arg, Expr)
                    actual = arg.args[0]
                    if actual.kind != 'role' or arg.value in arguments:
                        fail('pattern arguments must be unique named roles', clause)
                    arguments[arg.value] = mapping.get(actual.value, actual.value)
                names = {p.role for p in target.parameters}
                if len(names) != len(target.parameters):
                    fail('duplicate pattern parameter', clause)
                if arguments.keys() - names:
                    fail('unknown pattern argument', clause)
                counter += 1
                prefix = f'@{counter}:'
                local_names = _roles(target.clauses) | names
                local = {name: prefix + name for name in local_names}
                for param in target.parameters:
                    if param.type.name not in domains or param.type.arguments:
                        fail('unsupported pattern role type', clause)
                    if param.direction == 'in' and (param.role not in arguments or arguments[param.role] not in roles):
                        fail('pattern input must already be bound', clause)
                    if param.role in arguments:
                        local[param.role] = arguments[param.role]
                lower(target.clauses, local, owner, stack + (clause.name,), {p.role:domains[p.type.name] for p in target.parameters})
                for param in target.parameters:
                    if local[param.role] not in roles:
                        fail('pattern output has no finite binding', clause)
                    kind = roles[local[param.role]]
                    expected = domains[param.type.name]
                    compatible = (kind == expected if expected.startswith('enum:') else
                        kind in KINDS and set(KINDS[kind]) <= set(KINDS[expected]) and {kind,expected} != {'param','receiver'})
                    if not compatible:
                        fail('pattern parameter type does not match binding', clause)
            elif clause.kind in ('fields', 'parameters') and not clause.flags:
                lower(clause.blocks[0], mapping, owner, stack, expected_types)
            elif clause.kind in ('fields', 'parameters') and clause.flags == ('exact',):
                if owner is None:
                    fail('exact inventory requires an owner', clause)
                expected_selector = 'field' if clause.kind == 'fields' else 'param'
                valid_owners = ('type', 'class', 'interface', 'trait') if expected_selector == 'field' else ('callable', 'method', 'function', 'constructor')
                if roles[owner] not in valid_owners:
                    fail('exact inventory has incompatible owner type', clause)
                children = clause.blocks[0]
                if any(c.kind != 'selector' or c.name != expected_selector for c in children):
                    fail('exact inventory requires direct field or parameter selectors', clause)
                lower(children, mapping, owner, stack, expected_types)
                counter += 1
                role = f'@inventory:{counter}'
                item = Expr('role', clause.span, role)
                parent = Expr('role', clause.span, owner)
                domain = Expr('call', clause.span, 'owns', tuple(Expr('argument', clause.span, args=(a,)) for a in (parent, item)))
                allowed = Expr('literal', clause.span, 'false')
                for child in children:
                    equal = Expr('binary', child.span, '==', (item, Expr('role', child.span, mapping.get(child.role, child.role))))
                    allowed = Expr('binary', child.span, 'or', (allowed, equal))
                condition = Expr('quantifier', clause.span, 'forall', (domain, allowed),
                                 (Parameter(TypeName('Field' if expected_selector == 'field' else 'Parameter'), role),))
                filters.append(condition)
                actions.append(('', condition))
                steps.append(Action('',condition))
            else:
                fail(f'{clause.kind} evaluation is not implemented', clause)

    lower(selected.clauses, {})
    if len(steps) > 256:
        raise CompileError('execution pipeline depth limit exceeded', tree.span, 'resource_limit')
    if len(scans) > 96:
        fail('structural join depth limit exceeded')
    def check(expr: Expr) -> str:
        if expr.kind == 'type_test':
            if check(expr.args[0]) != 'SourceType':
                fail('type matcher requires a source type',expr)
            try:
                validate_matcher(expr.args[1])
            except ParseError as exc:
                raise CompileError(str(exc),exc.span) from exc
            return 'Bool'
        if expr.kind == 'literal':
            import json
            if expr.value == 'undefined':
                fail('undefined scalar calculation is not supported', expr)
            val = json.loads(expr.value)
            if isinstance(val, float) and not math.isfinite(val):
                fail('nonfinite numeric literal', expr)
            return {str:'String', bool:'Bool', int:'Int', float:'Float', type(None):'Null'}[type(val)]
        if expr.kind == 'role':
            if expr.value not in roles:
                fail(f'unbound role ${expr.value}', expr)
            if roles[expr.value]=='#computed':
                if expr.value not in computed_types:
                    fail('calculated role used before its definition',expr)
                return computed_types[expr.value]
            return roles[expr.value] if roles[expr.value].startswith('enum:') else 'Entity'
        if expr.kind == 'name':
            name, _, member = expr.value.rpartition('.')
            if name in enums and member in enums[name]:
                return 'enum:' + name
            fail('unknown enum member', expr)
        if expr.kind == 'regex':
            return 'Regex'
        if expr.kind == 'member' and len(expr.args) == 1 and expr.args[0].kind == 'role':
            check(expr.args[0])
            kind = roles[expr.args[0].value]
            if kind not in PROPERTIES or expr.value not in PROPERTIES[kind]:
                fail('unsupported property accessor', expr)
            return PROPERTIES[kind][expr.value]
        if expr.kind == 'list':
            types = {check(a) for a in expr.args}
            if not types:
                return 'List<Empty>'
            if len(types) == 1:
                return 'List<' + next(iter(types)) + '>'
            fail('membership list requires homogeneous types', expr)
        if expr.kind == 'unary':
            operand=check(expr.args[0])
            if expr.value=='not' and operand=='Bool':
                return 'Bool'
            if expr.value in ('+','-') and operand in ('Int','Float'):
                return operand
        if expr.kind in ('aggregate','quantifier'):
            before=dict(roles)
            try:
                for param in expr.parameters:
                    if param.role in roles or param.type.name not in domains or param.type.arguments:
                        fail('quantified role must be fresh with a finite domain',expr)
                    roles[param.role]=domains[param.type.name]
                if check(expr.args[0])!='Bool':
                    fail('quantifier condition must be Bool',expr)
                if expr.value=='exists':
                    return 'Bool'
                projected=check(expr.args[1])
                if expr.value=='forall':
                    if projected!='Bool':
                        fail('forall property must be Bool',expr)
                    return 'Bool'
                if expr.value=='count':
                    return 'Int'
                if projected not in ('Int','Float'):
                    fail('numeric aggregate requires numeric projection',expr)
                return projected if expr.value in ('sum','sum_by') else 'Option<'+('Float' if expr.value=='avg' else projected)+'>'
            finally:
                roles.clear(); roles.update(before)
        if expr.kind=='call' and expr.value=='stable_id' and len(expr.args)==1 and check(expr.args[0].args[0])=='Entity':
            return 'String'
        if expr.kind == 'call' and expr.value in signatures:
            signature = signatures[expr.value]
            if len(expr.args) != len(signature.parameters) or any(a.value for a in expr.args):
                fail('predicate requires positional arguments matching its signature', expr)
            for arg, param in zip(expr.args, signature.parameters):
                actual = arg.args[0]
                if param.type.name in enums:
                    if check(actual) != 'enum:' + param.type.name:
                        fail('predicate enum argument type mismatch', actual)
                    continue
                if check(actual) != 'Entity' or actual.kind != 'role':
                    fail('predicate argument must be a bound entity role', actual)
                kind = roles[actual.value]
                expected_kind = TYPES[param.type.name]
                if kind not in KINDS or not set(KINDS[kind]) <= set(KINDS[expected_kind]):
                    fail('predicate argument does not match its declared domain', actual)
                if {kind, expected_kind} == {'param', 'receiver'}:
                    fail('receiver and ordinary parameter are distinct domains', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value in UNARY_RELATIONS:
            if len(expr.args) != 1 or expr.args[0].value:
                fail('unary semantic relation expects one positional argument', expr)
            actual = expr.args[0].args[0]
            if (check(actual) != 'Entity' or actual.kind != 'role'
                    or roles[actual.value] not in KINDS
                    or not set(KINDS[roles[actual.value]]) <= set(KINDS['callable'])):
                fail('unary semantic relation argument must be a Callable role', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value in STATEMENT_UNARY:
            if len(expr.args) != 1 or expr.args[0].value:
                fail('statement relation expects one positional argument', expr)
            actual = expr.args[0].args[0]
            if (check(actual) != 'Entity' or actual.kind != 'role'
                    or roles[actual.value] not in KINDS):
                fail('statement relation argument must be a bound entity role', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value in STATEMENT_RELATIONS:
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('statement relation expects two positional arguments', expr)
            for argument in expr.args:
                actual = argument.args[0]
                if (check(actual) != 'Entity' or actual.kind != 'role'
                        or roles[actual.value] not in KINDS):
                    fail('statement relation argument must be a bound entity role', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value in RELATIONS:
            _, left, right = RELATIONS[expr.value]
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('semantic relation expects two positional arguments', expr)
            for argument, expected in zip(expr.args,(left,right)):
                actual = argument.args[0]
                if check(actual) != 'Entity' or actual.kind != 'role' or roles[actual.value] not in KINDS or not set(KINDS[roles[actual.value]]) <= set(KINDS[TYPES[expected]]):
                    fail('semantic relation argument has wrong domain', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value == 'receives':
            # ``receives($parameter, $type)``: a call site hands the parameter a value
            # the declaration typed as that type, or the result of building one. Both
            # operands are entity roles, like the RELATIONS family above.
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('receives expects two positional arguments', expr)
            for argument in expr.args:
                actual = argument.args[0]
                if (check(actual) != 'Entity' or actual.kind != 'role'
                        or roles[actual.value] not in KINDS):
                    fail('receives argument must be a bound entity role', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value == 'preserves':
            # ``preserves($callable, $place)``: the callable returns the place it was
            # entered with, or a wrapper the place was loaded into. Read on the graph
            # plan, because the claim follows the callable's own return operations.
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('preserves expects two positional arguments', expr)
            for argument in expr.args:
                actual = argument.args[0]
                if (check(actual) != 'Entity' or actual.kind != 'role'
                        or roles[actual.value] not in KINDS):
                    fail('preserves argument must be a bound entity role', actual)
            return 'Bool'
        if expr.kind == 'call' and expr.value == 'instance_slot':
            # ``instance_slot($local, $shared)``: the class-local instance slot is a view
            # of the slot the declaring class holds. Both sides are storages, so the
            # claim takes entity roles whatever selector bound them.
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('instance_slot expects two positional arguments', expr)
            for argument in expr.args:
                actual = argument.args[0]
                if (check(actual) != 'Entity' or actual.kind != 'role'
                        or roles[actual.value] not in KINDS):
                    fail('instance_slot argument must be a bound entity role', actual)
            return 'Bool'
        if expr.kind=='call' and expr.value in ('contains','contains_direct','same_symbol','visible_at','initialized_at'):
            if len(expr.args)!=2 or any(a.value for a in expr.args):
                fail('AST relation requires two positional nodes',expr)
            if any(a.args[0].kind!='role' or roles.get(a.args[0].value) not in ('node','expression','statement') for a in expr.args):
                fail('AST relation arguments must be common AST nodes',expr)
            return 'Bool'
        if expr.kind == 'call' and expr.value in ('owns', 'kind_is'):
            if len(expr.args) != 2 or any(a.value for a in expr.args):
                fail('structural relation expects two positional arguments', expr)
            a, b = (check(arg.args[0]) for arg in expr.args)
            if a == 'Entity' and b == ('Entity' if expr.value == 'owns' else 'String'):
                return 'Bool'
            fail('structural relation argument type mismatch', expr)
        if expr.kind == 'call' and expr.value == 'in_directory' and len(expr.args) == 2:
            if any(a.value for a in expr.args):
                fail('in_directory takes positional arguments', expr)
            if check(expr.args[0].args[0]) == 'Entity' and check(expr.args[1].args[0]) == 'String':
                return 'Bool'
        if expr.kind == 'binary':
            a, b = (check(arg) for arg in expr.args)
            if expr.value in ('+','-','*','/','%') and a in ('Int','Float') and b in ('Int','Float'):
                return 'Float' if 'Float' in (a,b) or expr.value=='/' else 'Int'
            if expr.value == 'in' and b in ('List<Empty>', 'List<' + a + '>'):
                return 'Bool'
            if expr.value in ('and','or') and a == b == 'Bool':
                return 'Bool'
            if expr.value == 'matches' and a == 'String' and b == 'Regex':
                return 'Bool'
            if expr.value in ('==','!=') and a == b:
                return 'Bool'
            if expr.value in ('<','>','<=','>=') and (a == b == 'String' or a in ('Int','Float') and b in ('Int','Float')):
                return 'Bool'
        fail(f'unsupported or ill-typed query expression {expr.kind}', expr)
        raise AssertionError
    saved_roles = dict(roles)
    for predicate in predicates:
        roles.clear()
        roles.update((p.role, domains[p.type.name]) for p in predicate.parameters)
        if check(predicate.formula) != 'Bool':
            fail('predicate formula must be Bool', predicate.formula)
    roles.clear()
    roles.update(saved_roles)
    for role,expr in actions:
        if role:
            computed_types[role]=check(expr)
        elif check(expr)!='Bool':
            fail('where requires Bool',expr)
    for scan in scans:
        for prop, value in scan.properties:
            if value.kind == 'wildcard':
                continue
            expected = PROPERTIES[scan.selector][prop]
            if expected == 'SourceType':
                try:
                    validate_matcher(value)
                except ParseError as exc:
                    raise CompileError(str(exc),exc.span) from exc
                continue
            actual = check(value)
            if actual != expected and not (actual == 'Regex' and expected == 'String'):
                fail(f'property {prop} expects {expected}, got {actual}', value)
    for expr in filters:
        if check(expr) != 'Bool':
            fail('where requires Bool', expr)
    for expr in optional:
        if check(expr) != 'Bool':
            fail('optional evidence requires Bool', expr)
    for step in steps:
        if isinstance(step,BodyPattern):
            for item in step.clauses:
                if item.kind == 'where':
                    condition = item.expressions[0]
                    assert isinstance(condition,Expr)
                    if check(condition) != 'Bool':
                        fail('BODY where requires Bool',condition)
    project = next(c for c in selected.clauses if c.kind == 'select')
    projection = tuple(e for e in project.expressions if isinstance(e, Expr))
    order = next((c for c in selected.clauses if c.kind == 'order'), None)
    ordering = tuple(e for e in order.expressions if isinstance(e, Expr)) if order else ()
    for projected in projection + ordering:
        check(projected.args[0])
    for ordered in ordering:
        result_type = check(ordered.args[0])
        if result_type not in ('String','Int','Float','Bool','Entity') and not result_type.startswith('enum:'):
            fail('order expression requires an ordered scalar or entity',ordered)
    limit = next((int(c.name) for c in selected.clauses if c.kind == 'limit'), None)
    key = sha256(repr((scans, filters, projection, ordering, limit, actions, predicates, optional, enums, steps)).encode()).hexdigest()
    return Program(selected.name, tuple(scans), tuple(filters), projection, ordering, limit, key,
                   actions=tuple(actions), predicates=predicates, optional=tuple(optional), enums=tuple(enums.items()), steps=tuple(steps))


def free_roles(expr: Expr) -> set[str]:
    found = {expr.value} if expr.kind == 'role' else set()
    for arg in expr.args:
        found.update(free_roles(arg))
    return found - {p.role for p in expr.parameters}


def _roles(clauses: tuple[Clause, ...]) -> set[str]:
    result: set[str] = set()
    def expression_roles(expr: Expr | SourceExpr) -> set[str]:
        found = {expr.value} if expr.kind == 'role' else set()
        for arg in expr.args:
            found.update(expression_roles(arg))
        return found
    for clause in clauses:
        for expr in clause.expressions:
            if isinstance(expr, (Expr,SourceExpr)):
                result.update(expression_roles(expr))
        if clause.alias:
            result.add(clause.alias)
        if clause.role:
            result.add(clause.role)
        result.update(p.role for p in clause.parameters)
        for block in clause.blocks:
            result |= _roles(block)
    return result


def compile(tree: File, query: str | None = None, *, libraries: Mapping[str, File] | None = None, relational: bool = False) -> Program:
    """Compile correlated alternatives, with a bounded distributive expansion.

    Each branch is checked independently: a branch-local role cannot escape
    unless every alternative binds it. The cap avoids an exponential compiler.
    """
    from .models import specialize
    from .libraries import resolve
    if libraries is None and any(name.startswith('ken.catalog.') for name in tree.imports):
        from .catalog import libraries as packaged_libraries
        libraries = {**packaged_libraries(), **(libraries or {})}
    for source in (tree, *(libraries or {}).values()):
        stack: list[tuple[object,int]] = [(source,0)]
        while stack:
            item, depth = stack.pop()
            if depth > 96:
                raise CompileError('compiled AST depth limit exceeded', source.span, 'resource_limit')
            if is_dataclass(item) and not isinstance(item,type):
                stack.extend((getattr(item,f.name),depth+1) for f in fields(item) if f.name != 'span')
            elif isinstance(item,tuple):
                stack.extend((child,depth) for child in item)
    try:
        tree = resolve(tree, libraries or {})
        tree = specialize(tree)
    except ParseError as exc:
        raise CompileError(str(exc), exc.span) from exc
    from .graph import has_graph, compile_graph
    if relational or has_graph(tree, query):
        return compile_graph(tree, query)
    expanded = _expand_file(tree, query)
    plans = tuple(_compile(t, query) for t in expanded)
    if len(plans) == 1:
        return plans[0]
    first = plans[0]
    return replace(first, branches=tuple(replace(p, limit=None) for p in plans),
                   fingerprint=sha256(''.join(p.fingerprint for p in plans).encode()).hexdigest())


def _expand_file(tree: File, query: str | None) -> tuple[File, ...]:
    declarations = {d.name: d for d in tree.declarations}
    if len(declarations) != len(tree.declarations):
        raise CompileError('duplicate declaration', tree.span)
    queries = [d for d in tree.declarations if d.kind == 'query' and (query is None or d.name == query)]
    if len(queries) != 1:
        raise CompileError('choose exactly one query', tree.span)
    definitions: list[Declaration] = []
    variants_by_name: dict[str, tuple[str, ...]] = {}

    def bound_size(size: int) -> None:
        if size > 128:
            raise CompileError('alternative expansion limit exceeded', tree.span, 'resource_limit')

    def variants_for(name: str, stack: tuple[str, ...]) -> tuple[str, ...]:
        if name in stack:
            raise CompileError('recursive pattern expansion is not supported', tree.span)
        if name in variants_by_name:
            return variants_by_name[name]
        decl = declarations.get(name)
        if decl is None or decl.kind != 'pattern':
            return (name,)
        variants = clauses(decl.clauses, stack + (name,))
        names = tuple(f'@variant:{name}:{i}' for i in range(len(variants)))
        definitions.extend(replace(decl, name=n, clauses=v) for n,v in zip(names,variants))
        variants_by_name[name] = names
        return names

    def clauses(items: tuple[Clause, ...], stack: tuple[str, ...] = ()) -> list[tuple[Clause, ...]]:
        variants: list[tuple[Clause, ...]] = [()]
        for item in items:
            choices: list[tuple[Clause, ...]] = []
            if item.kind == 'when':
                condition = item.expressions[0]
                assert isinstance(condition, Expr)
                positive = Clause('where', item.span, expressions=(condition,))
                negative = Clause('where', item.span, expressions=(Expr('unary', condition.span, 'not', (condition,)),))
                branches = item.blocks if len(item.blocks) == 2 else (*item.blocks, ())
                for guard, branch in zip((positive, negative), branches):
                    choices.extend((guard,) + rest for rest in clauses(branch, stack))
            elif item.kind == 'either':
                for branch in item.blocks:
                    choices.extend(clauses(branch, stack))
            elif item.kind in ('selector', 'fields', 'parameters'):
                choices = [(replace(item, blocks=(branch,)),) for branch in clauses(item.blocks[0], stack)]
            elif item.kind == 'use':
                choices = [(replace(item, name=name),) for name in variants_for(item.name, stack)]
            else:
                choices = [(item,)]
            bound_size(len(variants) * len(choices))
            variants = [prefix + choice for prefix in variants for choice in choices]
        return variants

    selected = queries[0]
    variants = clauses(selected.clauses)
    other = tuple(d for d in tree.declarations if d.kind not in ('query','pattern'))
    return tuple(replace(tree, declarations=(*other, *definitions, replace(selected,clauses=v))) for v in variants)
