"""Lower source-language selectors to relational operators, never query text.

Ownership is immediate and selector schemas are checked before inspecting a
project. This is shared by saved patterns and the semantic graph planner.
"""
from __future__ import annotations

import json
from dataclasses import replace

from .syntax import Clause, Expr

KINDS = {
    'class': 'CLASS', 'interface': 'INTERFACE', 'trait': 'INTERFACE',
    'type': 'CLASS|INTERFACE|TRAIT|STRUCT', 'module_decl': 'MODULE',
    'callable': 'CALLABLE', 'method': 'CALLABLE', 'constructor': 'CALLABLE',
    'field': 'STORAGE', 'param': 'PARAMETER', 'receiver': 'PARAMETER',
    # ``value`` captures a source value occurrence: a computed value or a named
    # constant read (enum member, module constant), which the IR publishes apart.
    'var': 'STORAGE', 'value': 'VALUE|MEMBER', 'operation': 'OPERATION', 'macro':'OPERATION', 'call': 'CALL',
    # ``type_parameter`` binds a name rather than an entity: the selector lowers
    # straight to BINDS_TYPE_PARAMETER, so this endpoint is never used.
    'type_parameter': 'TYPE_PARAMETER',
}
DOMAINS = {
    'TypeDecl': 'type', 'Module': 'module_decl', 'Callable': 'callable',
    'Field': 'field', 'Parameter': 'param', 'Receiver': 'receiver',
    'Binding': 'var', 'Value': 'value', 'Operation': 'operation', 'Call': 'call',
    'Entity': '', 'GraphTerm': '', 'Usage': 'usage',
}


def selector(clause: Clause, owner: tuple[str, str] | None) -> tuple[Clause, ...]:
    from .compiler import PROPERTIES
    from .graph import fail

    kind, role, span = clause.name, clause.role, clause.span
    if kind not in KINDS or clause.alias:
        fail('unsupported source selector or selector alias', clause)
    if kind == 'type_parameter':
        # ``type_parameter $t;`` names a generic parameter of the enclosing declaration.
        # The parameter is a *name*, so the IR publishes it as
        # ``BINDS_TYPE_PARAMETER(declaration, name)`` and the role binds that name;
        # ``type: parameter($t)`` later joins a place to the same name.
        # A declaration may be a type or a callable: a generic *method* declares its
        # own parameter (``<V> void accept(V visitor)``), and the IR binds the name to
        # that method, so the owning callable is the subject of the same relation.
        if owner is None or owner[1] not in ('type', 'class', 'interface', 'trait',
                                            'callable', 'method', 'function', 'constructor'):
            fail('type parameters require a generic declaration', clause)
        if any(p.kind != 'property' for p in clause.blocks[0]):
            fail('type parameters currently take no properties', clause)
        return (Clause('edge', span, name='BINDS_TYPE_PARAMETER',
                       expressions=(Expr('role', span, owner[0]), Expr('role', span, role)),
                       blocks=((),)),)
    if kind == 'macro':
        if owner is None or owner[1] not in ('callable','method','constructor'):
            fail('macro requires a callable owner',clause)
        if any(p.kind!='property' or p.name!='name' for p in clause.blocks[0]):
            fail('macro currently supports name',clause)
        if len(clause.blocks[0])>1:fail('duplicate macro name property',clause)
        name_role=Expr('role',span,role+'__macro_name')
        subject=Expr('role',span,role)
        macro_literal=lambda value: Expr('literal',span,json.dumps(value))
        def edge(name,a,b,properties=()):
            return Clause('edge',span,name=name,expressions=(a,b),blocks=(properties,))
        native=Clause('property',span,name='native_kind',expressions=(macro_literal('macro_invocation'),))
        macro_role=Clause('property',span,name='role',expressions=(macro_literal('macro'),))
        names=tuple(replace(p,name='text') for p in clause.blocks[0])
        return (edge('HAS_OPERATION',Expr('role',span,owner[0]),subject),
                edge('OPERATION',subject,Expr('wildcard',span,'_'),(native,)),
                edge('SYNTAX_PARENT',name_role,subject),
                edge('OPERATION',name_role,macro_literal('NATIVE'),(macro_role,*names)))
    if kind == 'receiver':
        if owner is None or owner[1] not in ('callable','method','constructor'):
            fail('receiver requires a callable owner',clause)
        result = [Clause('source_receiver',span,role=role,name=owner[0])]
        for prop in clause.blocks[0]:
            if (prop.kind != 'property' or prop.name != 'escapes' or
                    prop.expressions[0].kind != 'literal' or prop.expressions[0].value not in ('true','false')):
                fail('receiver accepts escapes: true or false',prop)
            result.append(Clause('source_type',span,role=role,name='escapes:'+owner[0],expressions=prop.expressions))
        return tuple(result)
    if kind == 'field':
        effective=[p for p in clause.blocks[0] if p.kind=='property' and p.name=='effective']
        if effective:
            if len(effective)!=1 or effective[0].expressions[0].kind!='literal' or effective[0].expressions[0].value not in ('true','false'):
                fail('effective requires a boolean literal',clause)
            properties=tuple(p for p in clause.blocks[0] if p not in effective)
            if effective[0].expressions[0].value=='true':
                if owner is None or owner[1] not in ('type','class','interface','trait'):
                    fail('effective field requires a type owner',clause)
                if any(p.kind!='property' or p.name not in ('name','type','static','visibility','declaration') for p in properties):
                    fail('effective field supports name, type, static, visibility and declaration',clause)
                if len({p.name for p in properties})!=len(properties):
                    fail('duplicate effective field property',clause)
                return (Clause('source_effective_field',span,role=role,name=owner[0],blocks=(properties,)),)
            clause=replace(clause,blocks=(properties,))
        if any(p.kind=='property' and p.name=='declaration' for p in clause.blocks[0]):
            fail('declaration requires effective: true',clause)
    subject = Expr('role', span, role)
    rows: list[Clause] = []

    def relation(name, a, b, properties=()):
        return Clause('edge', span, name=name, expressions=(a, b), blocks=(properties,))

    def literal(value):
        return Expr('literal', span, json.dumps(value))

    native = KINDS[kind]
    endpoint = (Expr('list', span, args=tuple(literal(x) for x in native.split('|')))
                if '|' in native else literal(native))
    if kind == 'operation':
        endpoint = Expr('wildcard', span, '_')
    props, nested, type_filters = [], [], []
    seen_properties = set()
    for child in clause.blocks[0]:
        if child.kind != 'property':
            nested.append(child)
            continue
        if child.name not in PROPERTIES.get(kind, {}):
            fail(f'unknown {kind} property {child.name}', child)
        if child.name in seen_properties:
            fail(f'duplicate {kind} property {child.name}',child)
        seen_properties.add(child.name)
        value = child.expressions[0]
        if child.name == 'visibility' and value.kind == 'name':
            if value.value not in ('public','private','protected','internal','package'):
                fail('unknown visibility', child)
            child = replace(child,expressions=(literal(value.value),))
            value = child.expressions[0]
        if value.kind == 'wildcard':
            continue
        if child.name == 'captures':
            if value.kind != 'role': fail('captures requires a binding role',child)
            # The property is the only place the captured binding is declared, so it
            # binds here as a value: the owner's own BODY names it to state what the
            # captured binding is used for. The CAPTURES edge below pins it to the
            # binding the language publishes.
            rows.append(Clause('source_capture',child.span,role=value.value))
            rows.append(relation('CAPTURES',subject,value))
            continue
        if child.name == 'exported':
            if value.kind != 'literal' or value.value != 'true':
                fail('exported currently requires true; absence of exports is not closed',child)
            exporter = Expr('role',span,owner[0]) if owner and owner[1] == 'module_decl' else Expr('wildcard',span,'_')
            rows.append(relation('EXPORT',exporter,subject))
            continue
        if kind == 'call' and child.name == 'result_family':
            family = value.value if value.kind == 'name' else value.value.strip('"') if value.kind == 'literal' else None
            if family not in ('scalar','unknown'):
                fail('result_family currently supports scalar or unknown',child)
            rows.append(relation('CALL_RESULT_KIND',subject,literal(family)))
            continue
        if kind == 'type' and child.name == 'derive':
            # ``derive: "Clone"`` names a derivation the compiler itself applies, which
            # the graph publishes as DERIVE_NAME(type, name).
            if value.kind not in ('literal','name'):
                fail('derive requires a name',child)
            spelling = json.loads(value.value) if value.kind == 'literal' and value.value.startswith('"') else value.value
            rows.append(relation('DERIVE_NAME',subject,literal(spelling)))
            continue
        if kind == 'call' and child.name == 'entry':
            # ``entry: $place`` states the binding the occurrence is entered with; the
            # graph publishes it as CALL_ENTRY_BINDING(call, place).
            if value.kind != 'role':
                fail('entry requires a place role',child)
            rows.append(relation('CALL_ENTRY_BINDING',subject,value))
            continue
        if kind == 'call' and child.name == 'receiver':
            # ``receiver: $place`` correlates the instance the call happens on; the
            # graph publishes it as RECEIVER(call, place).
            if value.kind != 'role':
                fail('receiver requires a place role',child)
            rows.append(relation('RECEIVER',subject,value))
            continue
        if kind == 'call' and child.name == 'resolution':
            # ``resolution: unresolved`` mirrors ``type_status``: a bare name is the
            # spelling of the status the occurrence publishes.
            status = (value.value if value.kind == 'name' else
                      value.value.strip('"') if value.kind == 'literal' else None)
            if status not in ('resolved','unresolved','ambiguous'):
                fail('resolution requires resolved, unresolved or ambiguous',child)
            props.append(Clause('property',span,name='resolution',expressions=(literal(status),)))
            continue
        if kind == 'call' and child.name == 'discarded':
            # ``discarded: true`` states that the result of this call is not consumed:
            # the graph publishes DISCARDS_RESULT(statement, call), and the statement
            # that drops the value is not what the pattern is about.
            if value.kind != 'literal' or value.value != 'true':
                fail('discarded currently requires true; the default is that the result is consumed',child)
            rows.append(relation('DISCARDS_RESULT',Expr('wildcard',span,'_'),subject))
            continue
        if kind == 'call' and child.name == 'target':
            if value.kind != 'role':
                fail('call target requires a Callable role',child)
            rows.append(Clause('either',span,blocks=(
                (relation('TARGET',subject,value),),
                (relation('DECLARED_TARGET',subject,value),))))
            continue
        if kind in ('class', 'interface', 'trait', 'type') and child.name == 'base':
            # ``base: $place`` states the runtime base of the declared type, which the
            # graph publishes as BASE_INPUT(type, place) when that place is an
            # unreassigned parameter of the declaring callable.
            if value.kind != 'role':
                fail('base requires a place role', child)
            rows.append(relation('BASE_INPUT', subject, value))
            continue
        if child.name in ('initial','writes'):
            if child.name == 'initial':
                if value.kind != 'literal' or value.value != 'null':
                    fail('initial currently supports null',child)
            else:
                if (value.kind != 'call' or value.value != 'exactly' or len(value.args) != 2
                        or any(a.kind != 'argument' or a.value or len(a.args) != 1 for a in value.args)
                        or value.args[0].args[0].kind != 'role'
                        or value.args[1].args[0].kind != 'literal'
                        or not value.args[1].args[0].value.isdigit()):
                    fail('writes requires exactly($binding, nonnegative_integer)',child)
            type_filters.append(Clause('source_type',span,role=role,name=child.name,expressions=(value,)))
            continue
        if child.name == 'reassigned':
            if value.kind != 'literal' or value.value not in ('true','false'):
                fail('reassigned requires a boolean',child)
            type_filters.append(Clause('source_type',span,role=role,name=child.name,expressions=(value,)))
            continue
        if child.name == 'completes':
            # ``completes: true``: the callable's body reaches a normal exit, so a body
            # that only throws or only leaves abruptly states the other value.
            if value.kind != 'literal' or value.value not in ('true','false'):
                fail('completes requires a boolean',child)
            type_filters.append(Clause('source_type',span,role=role,name=child.name,expressions=(value,)))
            continue
        if child.name in ('type', 'return_type', 'type_status', 'return_type_status'):
            # ``type: nominal($role)`` names the declared type entity, which the
            # graph publishes as TYPE(place, type). Native spellings such as
            # ``string`` still need the TypeRef vocabulary.
            argument = value.args[0] if value.kind == 'call' and len(value.args) == 1 else None
            if (child.name == 'return_type' and value.kind == 'call'
                    and value.value == 'applied' and len(value.args) == 2):
                # ``return_type: applied($unit, $state)`` states that the declared return
                # type applies the *enclosing* type to a type argument, which is exactly
                # when the graph publishes RETURN_TYPE_ARGUMENT(callable, argument).
                base, parameter = value.args
                if any(arg.kind != 'argument' or arg.value or len(arg.args) != 1
                       or arg.args[0].kind != 'role' for arg in (base, parameter)):
                    fail('applied requires the declaring type and a type argument role', child)
                if owner is not None and base.args[0].value != owner[0]:
                    fail('applied requires the enclosing type as its base', child)
                rows.append(relation('RETURN_TYPE_ARGUMENT', subject,
                                     Expr('role', span, parameter.args[0].value)))
                continue
            if (child.name == 'type' and value.kind == 'call' and value.value == 'nominal'
                    and argument is not None and argument.kind == 'argument' and not argument.value
                    and len(argument.args) == 1 and argument.args[0].kind == 'role'):
                rows.append(relation('TYPE', subject, Expr('role', span, argument.args[0].value)))
                continue
            if (child.name == 'type' and value.kind == 'call' and value.value == 'parameter'
                    and argument is not None and argument.kind == 'argument' and not argument.value
                    and len(argument.args) == 1 and argument.args[0].kind == 'role'):
                # ``type: parameter($t)`` states that the place's declared type *is* the
                # generic parameter ``$t`` names. Generic parameters have no entity, so
                # the graph publishes the spelling. The spelling differs by place: a
                # *parameter* whose declared type is one of its callable's type parameters
                # publishes TYPE_PARAMETER with the undecorated name, while any other place
                # (a field) publishes the type name as written -- ``Visitor &`` for a C++
                # reference -- so a field joins TYPE_NAME.
                spelling = 'TYPE_PARAMETER' if kind in ('param', 'receiver') else 'TYPE_NAME'
                rows.append(relation(spelling, subject, Expr('role', span, argument.args[0].value)))
                continue
            from .source_types import validate_matcher
            if child.name.endswith('_status'):
                if value.value.strip('"') not in ('known','unknown'):
                    fail('type status requires known or unknown', child)
            else:
                from .syntax import ParseError
                try:
                    validate_matcher(value)
                except ParseError as exc:
                    fail(str(exc),child)
            type_filters.append(Clause('source_type',span,role=role,name=child.name,expressions=(value,)))
            continue
        if kind == 'operation' and child.name == 'kind':
            if value.kind not in ('name', 'literal'):
                fail('operation kind requires a name', child)
            endpoint = literal(value.value.strip('"').upper())
        else:
            props.append(child)
    if kind == 'constructor':
        props.append(Clause('property', span, name='constructor', expressions=(literal(True),)))
    if kind == 'trait':
        props.append(Clause('property',span,name='native_kind',expressions=(literal('trait_item'),)))
    if kind in ('param', 'receiver'):
        props.append(Clause('property', span, name='receiver', expressions=(literal(kind == 'receiver'),)))
    rows.append(relation('OPERATION' if kind == 'operation' else 'ENTITY', subject, endpoint, tuple(props)))
    if owner:
        parent, parent_kind = owner
        type_owner = parent_kind in ('type', 'class', 'interface', 'trait')
        callable_owner = parent_kind in ('callable', 'method', 'constructor')
        ownership = ('HAS_METHOD' if type_owner and kind in ('method', 'constructor', 'callable') else
                     'HAS_FIELD' if type_owner and kind == 'field' else
                     'HAS_PARAMETER' if callable_owner and kind in ('param', 'receiver') else
                     'HAS_OPERATION' if callable_owner and kind == 'operation' else
                     'HAS_CALL' if callable_owner and kind == 'call' else
                     'DECLARES' if parent_kind == 'module_decl' or callable_owner and kind in ('var','callable','class','interface','trait','type') else None)
        if ownership is None:
            fail(f'{parent_kind} cannot immediately own {kind}', clause)
        rows.append(relation(ownership, Expr('role', span, parent), subject))
    elif kind in ('method', 'constructor', 'field'):
        # The domain remains immediate members even without an explicit parent.
        rows.append(relation('HAS_FIELD' if kind == 'field' else 'HAS_METHOD', Expr('wildcard', span, '_'), subject))
    # A selector's own filters are lowered after its declarations but before its body: a
    # ``writes: exactly($binding, n)`` filter names a binding the selector declares among
    # its children (``var $binding {}``), so those declarations must be in scope first,
    # while keeping the filter ahead of the body keeps the plan cheap.
    bodies: list[Clause] = []
    for child in nested:
        if child.kind == 'body':
            bodies.append(child)
            continue
        if child.kind in ('fields', 'parameters'):
            if child.flags:
                fail('exact member inventory in relational selectors is not implemented', child)
            rows.extend(Clause('source_owned', child.span, role=role, name=kind, blocks=((c,),)) for c in child.blocks[0])
        else:
            rows.append(Clause('source_owned', child.span, role=role, name=kind, blocks=((child,),)))
    rows.extend(type_filters)
    for child in bodies:
        rows.append(Clause('source_owned', child.span, role=role, name=kind, blocks=((child,),)))
    return tuple(rows)
