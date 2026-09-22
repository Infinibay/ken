"""Statement-CFG subsequence matching with explicit unsupported coverage."""
from __future__ import annotations

import ast
from bisect import bisect_right
from dataclasses import dataclass, replace
import json
import re
from typing import Callable, Iterator, NamedTuple

from ken.structural.model import Entity, IR, Operation
from ken.structural_store import Node, Store
from .cache import ArtifactCache
from .body_operations import operation_filter
from .semantic import SemanticRelations
from .source_optional import OPTIONAL_ROLES, optional_row
from .source_types import matches as matches_type, validate_matcher
from .source_expressions import binary_parts, matches_operator
from .syntax import Clause, Expr, SourceExpr, ParseError
from .values import OperationValue, QueryValue, Unknown, identity, is_unknown, conjunction, disjunction


def landed_place(producers: dict[str, str], semantic, value: QueryValue) -> str:
    """The place a call's result landed in: the local that call filled.

    ``let $batch = call $lookup { ... };`` names the local by the *call* that produced
    it, while the frontend publishes the write against the place the result went into
    (``ASSIGNED_FROM``). This resolves the one to the other, so a pattern states the
    provenance instead of the storage's spelling.

    Only an *unconditional* use of the role is safe: a local the code assigns again
    (``result = producer(); result = other; consume(result)``) no longer holds the call's
    result. The resolution is therefore offered only where the pattern names a *place* --
    an insertion collection, an insertion value or an indexed write target -- and never in
    argument position of an arbitrary call, where the caller's guard would have to be
    re-proved for every shape. An insertion value adds one allowance: a second producer
    that writes a *fresh* collection (``if batch == null: batch = []``) keeps the call's own
    result on the path that reads it.
    """
    if not isinstance(value,Node) or value.kind != 'VALUE' or not hasattr(semantic,'index'):
        return ''
    call_id = producers.get(value.local_id)
    if not call_id:
        return ''
    placed = {f.subject for f in semantic.index.rows('ASSIGNED_FROM') if f.object == call_id}
    return next(iter(placed)) if len(placed) == 1 else ''


def named_role(value: Expr | SourceExpr) -> str:
    """The role a ``name`` constraint binds, or ``''``.

    ``name: $action;`` reports whatever spelling the call uses; ``name: $action in
    ["insert", "update"];`` reports it and keeps the whitelist of primitive names a
    protocol is recognised under. Any other shape states spellings only.
    """
    if value.kind == 'role':
        return value.value
    if value.kind == 'binary' and value.value == 'in' and value.args and value.args[0].kind == 'role':
        return value.args[0].value
    return ''


def name_spellings(value: Expr | SourceExpr) -> tuple[str, ...] | None:
    """The callee spellings a ``name`` constraint states.

    A call occurrence's own spelling is one literal (``name: "clone"``) or, when
    the protocol is recognised under several primitive names, a list of
    alternatives (``name: ["copy", "deepcopy", "clone"]``). ``None`` means the
    value is not a spelling inventory this capability can read.
    """
    def decode(text: str) -> str:
        return json.loads(text) if text.startswith('"') else text
    if value.kind == 'literal':
        return (decode(value.value),)
    if value.kind == 'list' and value.args and all(arg.kind == 'literal' for arg in value.args):
        return tuple(decode(arg.value) for arg in value.args)
    return None


def name_regex(value: Expr | SourceExpr) -> re.Pattern[str] | None:
    """The regular expression a ``name`` constraint states, or ``None``.

    ``name: /(loads|parse|...)/;`` reads the callee spelling the way a graph-level
    ``edge`` matcher always could. The published spelling is the qualified path the
    source wrote -- Rust's ``serde_json::to_string``, C#'s ``Deserialize<string>`` --
    so a pattern that means "the codec's own reading" anchors on the segment that
    matters instead of enumerating every import path and type argument a project may
    spell. Length, backreference and lookaround limits are the ones the graph-level
    matcher enforces, so the two spellings stay equally regular.
    """
    if value.kind != 'regex':
        return None
    pattern, flags = value.value[1:].rsplit('/', 1)
    if len(pattern) > 512 or re.search(r'\\[1-9]|\(\?', pattern):
        raise ParseError('name regex must be regular (no backreferences or lookaround)', value.span)
    try:
        return re.compile(pattern, re.IGNORECASE if 'i' in flags else 0)
    except re.error:
        raise ParseError('name regex is not a valid expression', value.span)


@dataclass(frozen=True, slots=True)
class BodyPattern:
    owner: str
    clauses: tuple[Clause,...]
    adjacent: bool
    outputs: tuple[str,...]
    nested: tuple[tuple[Clause, BodyPattern], ...] = ()
    controls: tuple[tuple[Clause, tuple[BodyPattern, ...]], ...] = ()
    linear: bool = False
    call_aliases: tuple[str,...] = ()


@dataclass
class _State:
    group: str
    index: int
    bindings: dict[str,QueryValue]
    unknown: bool = False
    used: frozenset[str] = frozenset()
    last: str | None = None
    adjacent: bool = False
    protected: tuple[str,...] = ()
    forbidden_calls: tuple[str,...] = ()
    cursor: str | None = None


def terminal_bindings(clause: Clause) -> tuple[str,...]:
    roles = []
    for constraint in clause.blocks[0]:
        if constraint.kind != 'forbid':
            raise ParseError('terminal gap supports forbid assign(binding(...))',constraint.span)
        effect = constraint.expressions[0]
        if effect.kind != 'call' or effect.value != 'assign' or len(effect.args) != 1 or effect.args[0].value:
            raise ParseError('terminal gap supports forbid assign(binding(...))',constraint.span)
        place = effect.args[0].args[0]
        if place.kind != 'call' or place.value != 'binding' or len(place.args) != 1 or place.args[0].value or place.args[0].args[0].kind != 'role':
            raise ParseError('assign requires binding($role)',constraint.span)
        roles.append(place.args[0].args[0].value)
    if not roles:
        raise ParseError('terminal gap requires an assignment restriction',clause.span)
    return tuple(roles)


def protected_bindings(clause: Clause) -> tuple[str,...]:
    roles = []
    for constraint in clause.blocks[0]:
        if constraint.kind == 'property' and constraint.name == 'paths':
            value = constraint.expressions[0]
            if value.kind == 'name' and value.value == 'all' or value.kind == 'literal' and value.value == '"all"':
                continue
            raise ParseError('this gap requires paths: all',constraint.span)
        if constraint.kind != 'forbid':
            raise ParseError('unsupported interval effect',constraint.span)
        effect = constraint.expressions[0]
        if effect.kind == 'call' and effect.value == 'call':
            forbidden_targets(clause)
            continue
        if effect.kind != 'call' or effect.value != 'write' or len(effect.args) != 1 or effect.args[0].value:
            raise ParseError('this interval supports forbid write(binding(...))',constraint.span)
        binding = effect.args[0].args[0]
        if binding.kind != 'call' or binding.value != 'binding' or len(binding.args) != 1 or binding.args[0].value or binding.args[0].args[0].kind != 'role':
            raise ParseError('write requires an explicit binding',constraint.span)
        roles.append(binding.args[0].args[0].value)
    return tuple(roles)


def forbidden_targets(clause: Clause) -> tuple[str,...]:
    roles = []
    for constraint in clause.blocks[0]:
        if constraint.kind != 'forbid':
            continue
        effect = constraint.expressions[0]
        if effect.kind != 'call' or effect.value != 'call':
            continue
        args = effect.args
        if not args or args[0].value or args[0].args[0].kind != 'role' or len(args) > 2:
            raise ParseError('forbid call requires a bound Callable',constraint.span)
        if len(args) == 2 and (args[1].value != 'through' or args[1].args[0].value not in ('direct','"direct"')):
            raise ParseError('forbid call currently requires through: direct',constraint.span)
        roles.append(args[0].args[0].value)
    return tuple(roles)


def compile_body(clause: Clause, owner: str, mapping: dict[str,str], roles: dict[str,str], expected_types: dict[str,str] | None = None) -> BodyPattern:
    # The nested-clause loop below rebinds ``clause``; the BODY's own flags and span
    # must be captured here, or ``adjacent``/``linear`` and error spans would be read
    # from the last child clause instead of from the body being compiled.
    body_flags, body_span = clause.flags, clause.span
    outputs: list[str] = []
    expected_types = {mapping.get(k,k):v for k,v in (expected_types or {}).items()}
    call_aliases: list[str] = []
    nested: list[tuple[Clause, BodyPattern]] = []
    controls: list[tuple[Clause, tuple[BodyPattern, ...]]] = []
    def expression(e: Expr | SourceExpr) -> Expr | SourceExpr:
        args = tuple(expression(a) for a in e.args)
        name = mapping.get(e.value,e.value) if e.kind == 'role' else e.value
        if isinstance(e,Expr):
            assert all(isinstance(a,Expr) for a in args)
            return replace(e,value=name,args=tuple(a for a in args if isinstance(a,Expr)),
                           parameters=tuple(replace(p,role=mapping.get(p.role,p.role)) for p in e.parameters))
        return replace(e,value=name,args=args)
    def remap(c: Clause) -> Clause:
        return replace(c,role=mapping.get(c.role,c.role),alias=mapping.get(c.alias,c.alias),
                       expressions=tuple(expression(e) for e in c.expressions),
                       blocks=tuple(tuple(remap(c) for c in block) for block in c.blocks))
    clauses = tuple(remap(c) for c in clause.blocks[0])
    anchored = False
    pending_adjacent = False
    pending_gap = False
    for item in clauses:
        if item.kind == 'macro':
            if roles.get(item.role) not in ('macro','operation'):
                raise ParseError('macro requires a selected macro occurrence',item.span)
            anchored=True;pending_adjacent=False;pending_gap=False
            continue
        if item.kind == 'where':
            def free(e: Expr | SourceExpr) -> set[str]:
                found = {e.value} if e.kind == 'role' else set()
                for arg in e.args:
                    found.update(free(arg))
                return found - {p.role for p in e.parameters} if isinstance(e,Expr) else found
            if free(item.expressions[0]) - roles.keys():
                raise ParseError('BODY where inputs must already be bound',item.span)
            continue
        if item.kind == 'initializer':
            if anchored or item is not clauses[0] or item.alias:
                raise ParseError('initializer must be the first BODY step',item.span)
            for assignment in item.blocks[0]:
                if (assignment.kind != 'assign' or assignment.name != '=' or assignment.alias
                        or any(e.kind != 'role' for e in assignment.expressions)
                        or roles.get(assignment.expressions[0].value) != 'field'
                        or roles.get(assignment.expressions[1].value) != 'param'):
                    raise ParseError('initializer requires assignments from parameters to fields',assignment.span)
            if not item.blocks[0]:
                raise ParseError('initializer requires an assignment',item.span)
            anchored = True
            continue
        if item.kind == 'gap' and 'exit' in item.flags:
            if not anchored or item is not clauses[-1]:
                raise ParseError('terminal gap must follow an anchor and end BODY',item.span)
            for role in terminal_bindings(item):
                if roles.get(role) not in ('field','var','param','receiver'):
                    raise ParseError('terminal gap requires a bound source binding',item.span)
            continue
        if item.kind == 'gap':
            if not anchored or pending_gap:
                raise ParseError('gap requires two distinct anchors',item.span)
            for role in protected_bindings(item):
                if roles.get(role) not in ('var','param','receiver','field'):
                    raise ParseError('gap requires a bound storage',item.span)
            for role in forbidden_targets(item):
                if roles.get(role) not in ('callable','method','function','constructor'):
                    raise ParseError('gap call requires a bound Callable',item.span)
            pending_gap = True
            continue
        if item.kind == 'adjacent':
            if not anchored or pending_adjacent:
                raise ParseError('adjacent requires two distinct anchors',item.span)
            pending_adjacent = True
            continue
        if item.kind == 'if':
            def condition(e, capture: bool = True):
                if e.kind == 'call' and e.value == 'binary':
                    # ``if (binary(left: $event, operator: _, right: _))``: the condition
                    # compares the bound place with anything, under any operator. The
                    # frontend publishes the comparison the source wrote; the pattern
                    # claims the test, not its spelling.
                    left, _operator, right = binary_parts(e)
                    condition(left, capture)
                    condition(right, capture)
                    return
                if e.kind not in ('role','literal','binary','unary','wildcard','index'):
                    raise ParseError('unsupported condition expression',e.span)
                if e.kind == 'index':
                    # ``if ($pool[$key] == null)``: the guard tests *a read of a place*
                    # at a key. The container is a bound place and the key a bound
                    # operand, a fresh role, a literal or a wildcard -- the same claim
                    # an indexed walk or an indexed read states.
                    container = e.args[0]
                    key = e.args[1]
                    if container.kind != 'role' or roles.get(container.value) not in ('var','field','param','receiver','value'):
                        raise ParseError('condition requires a bound collection place',e.span)
                    if key.kind == 'role' and key.value not in roles:
                        if not capture or expected_types.get(key.value) not in ('value','call'):
                            raise ParseError('condition key requires a bound operand',e.span)
                        roles[key.value] = 'value'
                        if key.value not in outputs:
                            outputs.append(key.value)
                    elif key.kind == 'role' and roles.get(key.value) not in ('var','field','param','receiver','value'):
                        raise ParseError('condition key requires a bound operand',e.span)
                    elif key.kind not in ('role','literal','wildcard','member'):
                        raise ParseError('condition key requires a bound operand',e.span)
                    return
                if e.kind == 'role' and e.value not in roles:
                    if not capture or expected_types.get(e.value) not in ('value','call'):
                        raise ParseError('condition requires a bound source binding or captured value',e.span)
                    # A condition names the value it compares against: capture it
                    # from the occurrence instead of scanning every value.
                    roles[e.value] = 'value'
                    if e.value not in outputs:
                        outputs.append(e.value)
                elif e.kind == 'role' and roles.get(e.value) not in ('var','field','param','receiver','value'):
                    raise ParseError('condition requires a bound source binding or captured value',e.span)
                for child in e.args:
                    condition(child, capture)
            condition(item.expressions[0])
            arms=[]
            for arm in item.blocks:
                local=dict(roles)
                arm_pattern=compile_body(Clause('body',item.span,blocks=(arm,),flags=('linear',) if 'linear' in clause.flags else ()),owner,{},local,expected_types=expected_types) if arm else BodyPattern(owner,(),False,())
                arms.append(arm_pattern)
                for name in arm_pattern.outputs:
                    if name in expected_types and name not in outputs:
                        roles[name]=local[name];outputs.append(name)
            if item.alias:
                # ``if ($tag == _) as $branch { ... }``: the pattern names the branch
                # occurrence, the operation the condition opens.
                if item.alias in roles:
                    raise ParseError('branch capture must be fresh',item.span)
                roles[item.alias] = 'operation'
                outputs.append(item.alias)
            arms=tuple(arms)
            controls.append((item,arms))
            anchored = True
            pending_adjacent = pending_gap = False
            continue
        if item.kind == 'iterate':
            iteration_source = item.expressions[0]
            if iteration_source.kind == 'index':
                # ``iterate $registry[$topic] as $item``: the container is a bound place
                # and the key a bound operand, so the walk names the bucket it selects.
                container = iteration_source.args[0]
                key = iteration_source.args[1]
                if container.kind != 'role' or roles.get(container.value) not in ('var','field','param','receiver','value'):
                    raise ParseError('iterate requires a bound collection place',item.span)
                if key.kind == 'role' and roles.get(key.value) not in ('var','field','param','receiver','value'):
                    raise ParseError('iterate key requires a bound operand',item.span)
                if key.kind not in ('role','literal','member'):
                    raise ParseError('iterate key requires a bound operand',item.span)
            elif iteration_source.kind != 'role' or roles.get(iteration_source.value) not in ('var','field','param','receiver','value','call'):
                if iteration_source.kind == 'role' and iteration_source.value not in roles:
                    # ``iterate $source as $item`` names the collection the walk reads:
                    # an unbound role is introduced here, so a pattern can expose
                    # whatever the loop walks instead of first requiring a bound place.
                    roles[iteration_source.value]='value'
                    if iteration_source.value not in outputs:
                        outputs.append(iteration_source.value)
                else:
                    raise ParseError('iterate requires a bound collection',item.span)
            if item.name or item.role in roles:
                raise ParseError('iterate requires a fresh element role; collection output is not implemented',item.span)
            bodies = [c for c in item.blocks[0] if c.kind == 'body']
            properties=[c for c in item.blocks[0] if c.kind=='property']
            if len(bodies)!=1 or len(bodies)+len(properties)!=len(item.blocks[0]):
                raise ParseError('iterate requires exactly one BODY and supported properties',item.span)
            async_properties=[p for p in properties if p.name=='async']
            body_properties=[p for p in properties if p.name=='body']
            origin_properties=[p for p in properties if p.name=='origin']
            if (len(async_properties)>1 or len(body_properties)>1 or len(origin_properties)>1
                    or len(async_properties)+len(body_properties)+len(origin_properties)!=len(properties)):
                raise ParseError('iterate supports async: true or false, one body role and one origin role',item.span)
            if any(p.expressions[0].kind!='role' for p in origin_properties):
                raise ParseError('iterate origin names a call occurrence',item.span)
            if any(p.expressions[0].kind!='literal' or p.expressions[0].value not in ('true','false') for p in async_properties):
                raise ParseError('iterate supports async: true or false',item.span)
            if body_properties:
                # ``iterate $collection as $item as $loop { body: $body; body {...} }``
                # names the body region of the walk: the pattern can then hand the loop
                # body on as an Operation instead of only constraining what happens
                # inside it.
                body_expression=body_properties[0].expressions[0]
                if body_expression.kind!='role':
                    raise ParseError('iterate body names a role',item.span)
                if body_expression.value in roles:
                    raise ParseError('iteration body capture must be fresh',item.span)
                roles[body_expression.value]='operation';outputs.append(body_expression.value)
            if item.alias:
                if item.alias in roles:raise ParseError('iteration capture must be fresh',item.span)
                roles[item.alias]='operation';outputs.append(item.alias)
            local = {**roles,item.role:'value'}
            inner=compile_body(replace(bodies[0],flags=(*bodies[0].flags,'linear')) if 'linear' in clause.flags else bodies[0],owner,{},local,expected_types=expected_types) if bodies[0].blocks[0] else BodyPattern(owner,(),False,())
            nested.append((item,inner))
            for name in inner.outputs:
                if name in expected_types and name not in outputs:
                    roles[name]=local[name];outputs.append(name)
            if item.role in expected_types:
                if expected_types[item.role] not in ('var',''):
                    raise ParseError('iteration element output requires Binding',item.span)
                roles[item.role]=expected_types[item.role] or 'var';outputs.append(item.role)
            anchored = True
            pending_adjacent = pending_gap = False
            continue
        if item.kind not in ('assign','return','yield','break','selector','call','let','insert','clear') or item.kind == 'selector' and item.name != 'var':
            raise ParseError('BODY instruction is not implemented: ' + item.kind,item.span)
        if item.kind == 'selector':
            if item.role in roles and roles[item.role] != 'var':
                raise ParseError('var capture requires a Binding role',item.span)
            if item.role not in roles:
                roles[item.role] = 'var'; outputs.append(item.role)
            for prop in item.blocks[0]:
                if prop.kind != 'property' or prop.name not in ('name','type','type_status'):
                    raise ParseError('unsupported variable property',prop.span)
                if prop.name == 'type':
                    value = prop.expressions[0]
                    assert isinstance(value,Expr)
                    validate_matcher(value)
                elif prop.name == 'name':
                    value = prop.expressions[0]
                    if not isinstance(value,Expr) or value.kind not in ('literal','regex','wildcard') or value.kind == 'literal' and not isinstance(json.loads(value.value),str):
                        raise ParseError('variable name requires string or regex',prop.span)
                elif prop.name == 'type_status':
                    value = prop.expressions[0]
                    if not isinstance(value,Expr) or (value.value if value.kind == 'name' else json.loads(value.value) if value.kind == 'literal' else None) not in ('known','unknown'):
                        raise ParseError('type_status requires known or unknown',prop.span)
        def source(e: Expr | SourceExpr, allow_value: bool = False, capture: bool = False) -> None:
            if e.kind == 'call' and e.value == 'binary':
                left,operator,right = binary_parts(e)
                source(left,allow_value,capture); source(right,allow_value,capture)
                return
            if e.kind == 'call' and e.value == 'read' and len(e.args) == 1 and not e.args[0].value and e.args[0].args[0].kind == 'role':
                source(e.args[0].args[0],allow_value,capture)
                return
            if e.kind == 'member':
                # ``$place.name`` addresses a member of a retained place; ``$place.$field``
                # reads the same member through the pattern's own declaration role, so the
                # member's spelling stays out of the query. Either way the member
                # declaration is resolved against the pattern's bound fields.
                place = e.args[0] if e.args else None
                if (place is None or place.kind != 'role'
                        or roles.get(place.value) not in ('field','var','param','receiver','value')
                        or len(e.args) > 2
                        or len(e.args) == 2 and (e.args[1].kind != 'role'
                                                 or roles.get(e.args[1].value) not in ('field','var'))):
                    raise ParseError('member requires a bound place',e.span)
                return
            if e.kind == 'index':
                # ``$container[$key]``: the operand is an element of a container place. The
                # container is what the pattern bound; the key is an ordinary source operand,
                # or the anonymous ``_`` when any element of the container will do.
                container, key = e.args[0], e.args[1]
                if container.kind != 'role' or roles.get(container.value) not in (
                        'var','param','receiver','field','value','callable'):
                    raise ParseError('index requires a bound container place',e.span)
                if key.kind == 'role':
                    if key.value not in roles:
                        # An unbound key is the key this access uses: the element origin is
                        # stated without enumerating every key in the project.
                        if not (capture or allow_value):
                            raise ParseError('index key requires a bound operand',e.span)
                        roles[key.value] = 'value'
                        if key.value not in outputs:
                            outputs.append(key.value)
                    elif roles[key.value] not in ('var','param','receiver','field','value'):
                        raise ParseError('index key requires a bound operand',e.span)
                elif key.kind not in ('literal','wildcard','member'):
                    raise ParseError('index key requires a bound operand',e.span)
                return
            if e.kind not in ('role','literal','binary','unary','wildcard'):
                raise ParseError('unsupported source expression',e.span)
            allowed = ('var','param','receiver','field') if not allow_value else ('var','param','receiver','field','value','callable','call')
            if e.kind == 'role' and e.value not in roles:
                if not capture or expected_types.get(e.value) not in ('value','call'):
                    # Only a role the pattern *declared* as a produced value is
                    # captured: an undeclared name is a typo, not evidence.
                    raise ParseError('source operand requires a bound storage, parameter or captured value'
                                     if allow_value else 'source operand requires a bound storage or parameter',e.span)
                # The effect captures the value it mentions: an assignment or a
                # comparison names the written/compared value by occurrence, so a
                # pattern states it without enumerating every value in the project.
                roles[e.value] = 'value'
                if e.value not in outputs:
                    outputs.append(e.value)
            elif e.kind == 'role' and roles[e.value] not in allowed:
                raise ParseError('source operand requires a bound storage, parameter or captured value'
                                 if allow_value else 'source operand requires a bound storage or parameter',e.span)
            for arg in e.args:
                source(arg,allow_value,capture)
        for position,e in enumerate(item.expressions):
            # ``return $captured`` and ``$slot = $captured`` consume a produced value.
            # The right-hand side of an assignment may name a value the pattern has
            # not bound: BODY captures it from that occurrence.
            source(e,allow_value=True,capture=item.kind == 'assign' and position == len(item.expressions) - 1)
        for block in item.blocks:
            for clause in block:
                if clause.kind == 'from' and roles.get(clause.role) not in (
                        'var','param','receiver','field','value','callable','call','operation'):
                    # ``return from $forward;``: the returned value consumes a place the
                    # pattern bound -- the delegated call whose result it transforms.
                    raise ParseError('derivation requires a bound place',clause.span)
        if item.kind == 'insert':
            # ``insert $value into $collection [at $key];`` — a collection effect. The
            # value and key are ordinary source operands (validated above); the
            # collection must be a place the pattern bound.
            if roles.get(item.role) not in ('field','var','param','receiver','value'):
                if item.role in roles:
                    raise ParseError('insert requires a bound collection place',item.span)
                roles[item.role] = expected_types.get(item.role) or 'value'
                if item.role not in outputs:
                    outputs.append(item.role)
            anchored = True
            pending_adjacent = pending_gap = False
            continue
        if item.kind == 'clear':
            # ``clear $collection after $iteration as $reset;`` — the drain closes by
            # emptying the same collection the walk bound, in the same block after it.
            if roles.get(item.role) not in ('field','var','param','receiver','value'):
                raise ParseError('clear requires a bound collection place',item.span)
            if item.name and roles.get(item.name) != 'operation':
                raise ParseError('clear requires a bound iteration operation',item.span)
            if item.alias:
                if item.alias in roles:
                    raise ParseError('clear evidence capture must be fresh',item.span)
                roles[item.alias] = 'operation'; outputs.append(item.alias)
            anchored = True
            pending_adjacent = pending_gap = False
            continue
        if item.kind == 'let':
            # ``let $result = call $target { ... } as $invocation;`` captures the value
            # produced by that call. It does not describe a source ``let`` binding.
            inner = item.blocks[0][0] if item.blocks and len(item.blocks[0]) == 1 else None
            if inner is None and len(item.expressions) == 1 and item.expressions[0].kind == 'index':
                # ``let $value = $container[$key];`` captures the element an indexed read
                # yields: the container is a place the pattern bound and the key the operand
                # it selects, exactly as for an indexed argument. The named role is the
                # element itself, so the pattern can return or compare it without naming the
                # whole collection.
                if item.role in roles and roles[item.role] != 'value':
                    raise ParseError('let capture requires a Value role',item.span)
                if item.role not in roles:
                    roles[item.role] = 'value'
                if item.role not in outputs:
                    outputs.append(item.role)
                if item.alias:
                    # ``as $read`` names the read occurrence itself, so a pattern can
                    # order it against the other steps of the same cursor.
                    if item.alias in roles:
                        raise ParseError('operation evidence capture must be fresh',item.span)
                    roles[item.alias] = 'operation'
                    outputs.append(item.alias)
                anchored = True
                pending_adjacent = pending_gap = False
                continue
            if inner is None or inner.kind not in ('call','construct'):
                raise ParseError('let requires a call or a construction',item.span)
            if inner.kind == 'construct':
                if inner.role not in roles:
                    # ``construct $type`` binds the constructed type when the pattern
                    # does not name it: "there is a type this call constructs".
                    roles[inner.role] = 'type'
                    outputs.append(inner.role)
                elif roles[inner.role] not in ('type','class','interface','trait'):
                    raise ParseError('construct requires a bound type',item.span)
                for constraint in inner.blocks[0]:
                    if constraint.kind == 'initializer':
                        if roles.get(constraint.role) not in ('field','var','param','receiver'):
                            raise ParseError('initializer requires a bound storage role',constraint.span)
                        for operand in constraint.expressions:
                            # ``initializer $field from $value;`` names the stored value,
                            # so it must already be a place the pattern bound (a captured
                            # callable, a parameter, a value), never a fresh name.
                            source(operand,allow_value=True)
                        properties = constraint.blocks[0] if constraint.blocks else ()
                        if len(properties) > 1:
                            raise ParseError('initializer accepts one transfer property',constraint.span)
                        for prop in properties:
                            value = prop.expressions[0] if prop.expressions else None
                            if (prop.kind != 'property' or prop.name != 'transfer' or value is None
                                    or value.kind != 'list' or not value.args
                                    or any(a.kind != 'name' or a.value not in ('identity','shallow_copy') for a in value.args)):
                                raise ParseError('initializer transfer requires [identity, shallow_copy] or a subset',constraint.span)
                    elif constraint.kind == 'argument':
                        # ``argument $place at N;``: the value the construction was
                        # invoked with -- the context instance a state constructor
                        # retains, or the successor a setter is handed. The operand is
                        # a place the pattern bound, never a fresh name.
                        if constraint.role and roles.get(constraint.role) != 'param':
                            raise ParseError('argument for requires a bound Parameter',constraint.span)
                        given = [e for e in constraint.expressions if e.kind != 'from']
                        if given:
                            source(given[0],allow_value=True)
                    elif constraint.kind == 'where':
                        continue
                    elif constraint.kind == 'property' and constraint.name == 'retained':
                        # ``construct $type {} retained: $gap;``: the conditional's
                        # other arm hands the gap back, so the construction is the arm
                        # the null test takes when the value is missing.
                        source(constraint.expressions[0],allow_value=True)
                    else:
                        raise ParseError('unsupported construct constraint',constraint.span)
                if item.role in roles and roles[item.role] != 'value':
                    raise ParseError('let capture requires a Value role',item.span)
                if item.role not in roles:
                    roles[item.role] = 'value'
                if item.role not in outputs:
                    outputs.append(item.role)
                if item.alias:
                    if item.alias in roles:
                        raise ParseError('operation evidence capture must be fresh',item.span)
                    roles[item.alias] = 'operation'; outputs.append(item.alias)
                    if expected_types.get(item.alias) == 'call':
                        roles[item.alias] = 'call'; call_aliases.append(item.alias)
                anchored = True
                pending_adjacent = False
                pending_gap = False
                continue
            if inner.role not in roles:
                roles[inner.role] = 'callable'
                outputs.append(inner.role)
            if roles.get(inner.role) not in ('callable','method','function','constructor','call',
                                               'field','var','param','receiver','value'):
                raise ParseError('call requires a bound Callable target or a retained callable',item.span)
            for constraint in inner.blocks[0]:
                if constraint.kind == 'argument' and not constraint.alias:
                    if constraint.role and roles.get(constraint.role) != 'param':
                        raise ParseError('argument for requires a bound Parameter',constraint.span)
                    given = [e for e in constraint.expressions if e.kind != 'from']
                    if given:
                        source(given[0],allow_value=True)
                    for derived in (e for e in constraint.expressions if e.kind == 'from'):
                        # ``argument from $place;``: the operand is a computation over a place
                        # the pattern bound, so the place is what must be bound -- the operand
                        # itself is deliberately unnamed.
                        if roles.get(derived.value) not in ('var','param','receiver','field','value','callable','call'):
                            raise ParseError('derivation requires a bound place',derived.span)
                elif constraint.kind == 'property' and constraint.name == 'dispatch' and constraint.expressions[0].value in ('exact','possible','contract','"exact"','"possible"','"contract"'):
                    pass
                elif constraint.kind == 'property' and constraint.name == 'entry':
                    # ``entry: $place;`` states the binding this occurrence is entered with:
                    # the place still holds what it held before the call.
                    place = constraint.expressions[0]
                    if place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('entry requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'receiver':
                    place = constraint.expressions[0]
                    if place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('receiver requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'receiver_input':
                    # ``let $v = call $f { receiver_input: $place; };`` is the capture form of
                    # the stricter receiver reading: the receiver *expression* of this
                    # occurrence is that place itself, published as CALL_RECEIVER_INPUT.
                    place = constraint.expressions[0]
                    if place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('receiver_input requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'resolution' and constraint.expressions[0].value.strip('"') in ('resolved','unresolved','ambiguous','any'):
                    pass
                elif (constraint.kind == 'property' and constraint.name == 'name'
                        and named_role(constraint.expressions[0]) in expected_types and named_role(constraint.expressions[0])):
                    # ``name: $action;`` or ``name: $action in [..];`` reports the spelling
                    # this call dispatches to: the role the pattern declared carries it.
                    roles[named_role(constraint.expressions[0])] = 'value'
                    if named_role(constraint.expressions[0]) not in outputs:
                        outputs.append(named_role(constraint.expressions[0]))
                elif constraint.kind == 'property' and constraint.name == 'name' and (
                        name_spellings(constraint.expressions[0]) or name_regex(constraint.expressions[0])):
                    pass
                elif constraint.kind == 'property' and constraint.name == 'discarded' and constraint.expressions[0].value.strip('"') == 'true':
                    pass
                elif constraint.kind == 'property' and constraint.name == 'returned' and constraint.expressions[0].value.strip('"') == 'true':
                    pass
                elif constraint.kind == 'property' and constraint.name == 'unreplaced' and constraint.expressions[0].value.strip('"') == 'true':
                    # ``unreplaced: true;`` states that the place this occurrence is
                    # dispatched on was not rebound before it.
                    if not any(other.kind == 'property' and other.name == 'receiver'
                               for other in inner.blocks[0]):
                        raise ParseError('unreplaced requires the receiver place of the same call',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'rebound' and constraint.expressions[0].value.strip('"') in ('true','false'):
                    # ``rebound: true;`` waives the position check on an iteration
                    # binding: the walk dispatched on the element it iterated, and a write
                    # to the loop variable inside the walk does not change which element
                    # the binding names. The complement of ``unreplaced: true;``.
                    if not any(other.kind == 'property' and other.name == 'receiver'
                               for other in inner.blocks[0]):
                        raise ParseError('rebound requires the receiver place of the same call',constraint.span)
                elif constraint.kind == 'property' and constraint.name in OPTIONAL_ROLES:
                    # ``wraps: $v;`` / ``empty: $supplier;`` / ``present: $consumer;`` /
                    # ``fallback: $x;`` state what the Optional protocol call does with
                    # its operand. The same rows are read in ``call`` and in ``let ..
                    # call`` position, so both loops must accept them.
                    operand = constraint.expressions[0]
                    if operand.kind not in ('role','literal','name','wildcard'):
                        raise ParseError('optional row requires a role or literal',constraint.span)
                    if operand.kind == 'role' and operand.value not in roles:
                        roles[operand.value] = 'callable' if constraint.name in ('empty','present') else 'value'
                        # Naming the row's other side binds the role, so a later clause
                        # may state what that value *is* without the role dropping out
                        # of the pattern's outputs.
                        if operand.value not in outputs:
                            outputs.append(operand.value)
                else:
                    raise ParseError('unsupported call constraint',constraint.span)
            if item.role in roles and roles[item.role] != 'value':
                raise ParseError('let capture requires a Value role',item.span)
            if item.role not in roles:
                roles[item.role] = 'value'
            if item.role not in outputs:
                outputs.append(item.role)
        if item.kind == 'call':
            # ``call qualify $parameter { ... }`` names the declaration's own generic
            # parameter as the qualifier (C++ ``P::operation``): the role is a type
            # parameter, not a bound callable.
            qualified = 'qualify' in item.flags
            if item.role not in roles:
                roles[item.role] = 'type_parameter' if qualified else 'callable'
                outputs.append(item.role)
            accepted = (('type_parameter',) if qualified else
                        ('callable','method','function','constructor','call',
                         'field','var','param','receiver','value'))
            if roles.get(item.role) not in accepted:
                # A place can retain the callable value being invoked.
                raise ParseError('call requires a bound Callable target or a retained callable',item.span)
            for constraint in item.blocks[0]:
                if constraint.kind == 'argument' and not constraint.alias:
                    if constraint.role and roles.get(constraint.role) != 'param':
                        raise ParseError('argument for requires a bound Parameter',constraint.span)
                    given = [e for e in constraint.expressions if e.kind != 'from']
                    if given:
                        source(given[0],allow_value=True)
                    for derived in (e for e in constraint.expressions if e.kind == 'from'):
                        # ``argument from $place;``: the operand is a computation over a place
                        # the pattern bound, so the place is what must be bound -- the operand
                        # itself is deliberately unnamed.
                        if roles.get(derived.value) not in ('var','param','receiver','field','value','callable','call'):
                            raise ParseError('derivation requires a bound place',derived.span)
                elif constraint.kind == 'property' and constraint.name == 'dispatch' and constraint.expressions[0].value in ('exact','possible','contract','"exact"','"possible"','"contract"'):
                    pass
                elif constraint.kind == 'property' and constraint.name == 'entry':
                    # ``entry: $place;`` states the binding this occurrence is entered with:
                    # the place still holds what it held before the call.
                    place = constraint.expressions[0]
                    if place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('entry requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'receiver':
                    # ``receiver: $place;`` correlates the same instance, not its type.
                    # ``receiver: $place._;`` dispatches on a member of that place.
                    place = constraint.expressions[0]
                    if place.kind == 'member':
                        holder = place.args[0]
                        if holder.kind != 'role' or roles.get(holder.value) not in ('field','var','param','receiver','value'):
                            raise ParseError('receiver member requires a bound storage role',constraint.span)
                    elif place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('receiver requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'receiver_input':
                    # ``receiver_input: $place;`` requires the receiver *expression* of
                    # this occurrence to be that place itself, which is the stricter
                    # reading of ``receiver:``: it is published as CALL_RECEIVER_INPUT.
                    place = constraint.expressions[0]
                    if place.kind != 'role' or roles.get(place.value) not in ('field','var','param','receiver','value'):
                        raise ParseError('receiver_input requires a bound storage role',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'receiver_version':
                    # ``receiver_version: $lifetime;`` names the binding this occurrence
                    # reads the receiver place through. The first clause that names the
                    # role binds it; every later one must agree with that binding.
                    lifetime = constraint.expressions[0]
                    if lifetime.kind != 'role':
                        raise ParseError('receiver_version requires a role',constraint.span)
                    if lifetime.value not in roles:
                        roles[lifetime.value] = 'value'
                elif constraint.kind == 'property' and constraint.name == 'resolution' and constraint.expressions[0].value.strip('"') in ('resolved','unresolved','ambiguous','any'):
                    pass
                elif (constraint.kind == 'property' and constraint.name == 'name'
                        and named_role(constraint.expressions[0]) in expected_types and named_role(constraint.expressions[0])):
                    # ``name: $action;`` or ``name: $action in [..];`` reports the spelling
                    # this call dispatches to: the role the pattern declared carries it.
                    roles[named_role(constraint.expressions[0])] = 'value'
                    if named_role(constraint.expressions[0]) not in outputs:
                        outputs.append(named_role(constraint.expressions[0]))
                elif constraint.kind == 'property' and constraint.name == 'name' and (
                        name_spellings(constraint.expressions[0]) or name_regex(constraint.expressions[0])):
                    pass
                elif constraint.kind == 'property' and constraint.name == 'discarded' and constraint.expressions[0].value.strip('"') == 'true':
                    pass
                elif constraint.kind == 'property' and constraint.name == 'returned' and constraint.expressions[0].value.strip('"') == 'true':
                    pass
                elif constraint.kind == 'property' and constraint.name == 'unreplaced' and constraint.expressions[0].value.strip('"') == 'true':
                    # ``unreplaced: true;`` states that the place this occurrence is
                    # dispatched on was not rebound before it.
                    if not any(other.kind == 'property' and other.name == 'receiver'
                               for other in item.blocks[0]):
                        raise ParseError('unreplaced requires the receiver place of the same call',constraint.span)
                elif constraint.kind == 'property' and constraint.name == 'rebound' and constraint.expressions[0].value.strip('"') in ('true','false'):
                    # ``rebound: true;`` waives the position check on an iteration
                    # binding: the walk dispatched on the element it iterated, and a write
                    # to the loop variable inside the walk does not change which element
                    # the binding names. The complement of ``unreplaced: true;``.
                    if not any(other.kind == 'property' and other.name == 'receiver'
                               for other in item.blocks[0]):
                        raise ParseError('rebound requires the receiver place of the same call',constraint.span)
                elif constraint.kind == 'property' and constraint.name in OPTIONAL_ROLES:
                    operand = constraint.expressions[0]
                    if operand.kind not in ('role','literal','name','wildcard'):
                        raise ParseError('optional row requires a role or literal',constraint.span)
                    if operand.kind == 'role' and operand.value not in roles:
                        roles[operand.value] = 'callable' if constraint.name in ('empty','present') else 'value'
                        # Naming the row's other side binds the role, so a later
                        # clause may state what that value *is* without the role
                        # dropping out of the pattern's outputs.
                        if operand.value not in outputs:
                            outputs.append(operand.value)
                else:
                    raise ParseError('unsupported call constraint',constraint.span)
        if item.kind=='break' and roles.get(item.role)!='operation':
            raise ParseError('break requires a bound iteration capture',item.span)
        if item.kind == 'assign' and not (
                item.expressions[0].kind == 'role'
                and roles.get(item.expressions[0].value) in ('var','param','receiver','field')
                # ``$place.name`` writes a member of a bound place, which ``source``
                # above has already validated.
                # ``$registry[$key] = $value`` writes one element: the container is a bound
                # place and the key a bound operand, exactly as the indexed read states it.
                or item.expressions[0].kind in ('member', 'index')):
            raise ParseError('assignment place requires a bound storage role',item.span)
        if item.alias:
            if item.alias in roles:
                raise ParseError('operation evidence capture must be fresh',item.span)
            roles[item.alias] = 'operation'; outputs.append(item.alias)
            if expected_types.get(item.alias) == 'call':
                if item.kind not in ('call','let'):
                    raise ParseError('Call evidence requires a call or construction',item.span)
                roles[item.alias] = 'call'; call_aliases.append(item.alias)
        anchored = True
        pending_adjacent = False
        pending_gap = False
    if pending_adjacent or pending_gap or not anchored:
        raise ParseError('BODY requires anchors and cannot end with adjacent',body_span)
    return BodyPattern(owner,clauses,'adjacent' in body_flags,tuple(outputs),tuple(nested),tuple(controls),'linear' in body_flags,tuple(call_aliases))


class _BodyContext(NamedTuple):
    ir: IR
    operations: dict[str, Operation]
    children: dict[str, list[Operation]]
    local_nodes: tuple[Node, ...]
    calls: dict[tuple[int | None, int | None], Entity]
    operation_spans: dict[tuple[int, int], Operation]
    foreign_call_ids: frozenset[str]


class BodyEngine:
    def __init__(self, store: Store, snapshot: int, semantic: SemanticRelations,
                 check: Callable[[],None], regex: Callable[[str,Expr],bool],
                 evaluate: Callable[[Expr,dict[str,QueryValue]],QueryValue]):
        self.store,self.snapshot,self.semantic,self.check,self.regex = store,snapshot,semantic,check,regex
        self.units: ArtifactCache[IR] = ArtifactCache(8_000_000)
        self.contexts: ArtifactCache[_BodyContext] = ArtifactCache(8_000_000)
        self.evaluate = evaluate
        self.iteration_values: dict[str, tuple[Operation, str]] = {}
        # Loops whose walk hands over keys rather than values.
        self.keyed_iterations: set[str] = set()

    def source_unit(self, unit: int, owner: str | None) -> IR:
        from ken.structural_store.operations import load
        return load(self.store,unit,owner)

    def match_context(self, owner: Node, region: Operation | None) -> _BodyContext:
        """Owner-derived read-only maps shared across distinct BODY bindings."""
        ir, _ = self.units.get_or_compute(
            str(owner.unit) + ':' + owner.local_id,
            lambda: self.source_unit(owner.unit, owner.local_id),
        )
        reader = getattr(self.store, 'region_operations', None)
        candidates = reader(owner.local_id, region) if region is not None and reader is not None else ir.operations
        operations = {o.id: o for o in candidates if o.owner == owner.local_id
                      and (region is None or region.start <= o.start and o.end <= region.end)}
        children: dict[str, list[Operation]] = {}
        for op in operations.values():
            children.setdefault(op.parent or '', []).append(op)
        local_nodes = tuple(self.store.scan(self.snapshot, owner=owner))
        calls = {(e.attrs.get('start_byte'), e.attrs.get('end_byte')): e
                 for e in ir.entities.values() if e.kind == 'CALL' and e.attrs.get('owner') == owner.local_id}
        operation_spans = {(o.start, o.end): o for o in operations.values()}
        # Some grammars classify a call as another native kind (for example
        # Go indexed calls). The semantic occurrence's span still identifies it.
        call_spans = {(e.attrs.get('start_byte'), e.attrs.get('end_byte'))
                      for e in ir.entities.values() if e.kind == 'CALL'}
        foreign_call_ids = frozenset(o.id for o in operations.values()
                                     if o.kind != 'CALL' and (o.start, o.end) in call_spans)
        return _BodyContext(ir, operations, children, local_nodes, calls, operation_spans, foreign_call_ids)

    def match(self, pattern: BodyPattern, bindings: dict[str,QueryValue], *, region: Operation | None = None, linear_arm: bool = False) -> Iterator[tuple[dict[str,QueryValue],bool]]:
        if not pattern.clauses:
            yield bindings,False
            return
        owner = bindings[pattern.owner]
        if pattern.clauses[0].kind == 'initializer':
            from .constructor_initializers import matches as initializer_matches
            initial = initializer_matches(self.semantic,owner,pattern.clauses[0].blocks[0],bindings) if isinstance(owner,Node) else Unknown('initializer_owner_unknown')
            if initial is False:
                return
            remainder = replace(pattern,clauses=pattern.clauses[1:])
            for result,uncertain in self.match(remainder,bindings,region=region,linear_arm=linear_arm):
                yield result,uncertain or is_unknown(initial)
            return
        if not isinstance(owner,Node):
            yield {**bindings,**{r:Unknown('body_owner_unknown') for r in pattern.outputs}},True
            return
        if len(pattern.clauses) == 1 and pattern.clauses[0].kind == 'return':
            statement = pattern.clauses[0]
            value = bindings.get(statement.expressions[0].value) if statement.expressions and statement.expressions[0].kind == 'role' else None
            if isinstance(value,Node) and value.kind == 'CALLABLE' and not statement.alias:
                # An expression-bodied callable returns its body value. Its
                # nested function belongs to a different operation owner, so
                # it has no outer statement CFG to walk.
                implied = self.semantic.facts('BODY_VALUE',owner.local_id)
                if any(f.object == value.local_id for f in implied):
                    yield bindings,False
                    return
        statuses = self.semantic.facts('CFG_STATUS',owner.local_id)
        entries = self.semantic.facts('CFG_ENTRY',owner.local_id)
        from .source_coverage import supports_pattern
        if not entries or not supports_pattern(statuses, pattern):
            yield {**bindings,**{r:Unknown('control_flow_incomplete') for r in pattern.outputs}},True
            return
        context_key = repr((owner.unit, owner.local_id,
                            (region.id, region.start, region.end) if region is not None else None))
        context, _ = self.contexts.get_or_compute(context_key, lambda: self.match_context(owner, region))
        ir, operations, children, local_nodes, calls, operation_spans, foreign_call_ids = context
        # A nested function expression (lambda, arrow, func literal) parses as its own
        # callable and owns its sub-tree, so its root operation is missing from the
        # owner-filtered table above even though it is the *value* an enclosing
        # statement writes. Resolving such operands against the whole unit keeps the
        # written value visible without widening which operations a clause may match.
        whole_unit: dict[str,Operation] | None = None
        def unit_operation(operation_id: str) -> Operation | None:
            nonlocal whole_unit
            lookup = getattr(self.store, "operation", None)
            if lookup is not None:
                return lookup(operation_id)
            if whole_unit is None:
                whole_unit = {o.id:o for o in self.source_unit(owner.unit,None).operations}
            return whole_unit.get(operation_id)
        if region is not None:
            from ken.structural.model import Fact
            starts = [f.object for f in self.semantic.facts('CFG_NEXT',region.parent or '')
                      if f.object in operations]
            if not starts and region.id in operations:
                # The arm *is* the statement (``else if`` nests the branch inside an
                # else wrapper): its entry is the region itself, not a sibling edge.
                starts = [region.id]
            entries = [Fact(owner.local_id,'CFG_ENTRY',start) for start in starts]
            if not entries:
                if operations:
                    yield {**bindings,**{r:Unknown('iteration_entry_incomplete') for r in pattern.outputs}},True
                return
        nested_patterns = dict(pattern.nested)
        control_patterns = dict(pattern.controls)
        # Which call produced each captured value, for provenance of arguments.
        producers: dict[str,str] = {}
        boolean_results = None
        facts: dict[tuple[str,...],list] = {}
        def rows(relation: str, subject: str):
            key = (relation,subject)
            if key not in facts:
                facts[key] = self.semantic.facts(relation,subject)
            return facts[key]
        def rows_to(relation: str, object: str):
            # Reverse lookup. ``DISCARDS_RESULT(statement, call)`` is published with the
            # statement as subject, and a call clause holds the call, not the statement.
            key = ('to',relation,object)
            if key not in facts:
                facts[key] = self.semantic.facts_to(relation,object)
            return facts[key]
        def successors(group: str) -> tuple[str,...]:
            # The in-memory graph already indexes relation/subject pairs. Most
            # syntax children are operands, with no control-flow successor.
            index = getattr(self.semantic,'index',None)
            if index is not None and not index.rows('CFG_NEXT',group):
                return ()
            edges = rows('CFG_NEXT',group)
            candidate = operations.get(group)
            condition = rows('CONTROL_CONDITION',group) if candidate is not None and candidate.kind == 'BRANCH' else []
            if len(condition) == 1 and condition[0].object in operations:
                op = operations[condition[0].object]
                # Parentheses preserve a boolean literal's value; JS/TS
                # expose them as the condition node rather than the literal.
                seen_conditions=set()
                while op.native_kind in ('parenthesized_expression','condition_clause') and op.id not in seen_conditions:
                    seen_conditions.add(op.id)
                    operands=[c for c in children.get(op.id,()) if 'comment' not in c.native_kind]
                    if len(operands)!=1:break
                    op=operands[0]
                text = op.attrs.get('text')
                constant = {'True':True,'true':True,'False':False,'false':False}.get(text) if isinstance(text,str) else None
                if constant is not None:
                    rejected = 'false' if constant else 'true'
                    edges = [f for f in edges if f.attrs.get('kind') != rejected]
            return tuple(f.object for f in edges if region is None or f.object in operations)
        part_cache: dict[str,tuple[Operation,...]] = {}
        kind_cache: dict[tuple[str,frozenset[str]],tuple[Operation,...]] = {}
        def parts(group: str, kinds: frozenset[str] | None = None) -> tuple[Operation,...]:
            if group not in part_cache:
                self.check()
                todo = [operations[group]] if group in operations else []
                found = []
                while todo:
                    op = todo.pop()
                    self.check()
                    found.append(op)
                    todo.extend(c for c in children.get(op.id,()) if not successors(c.id))
                part_cache[group] = tuple(found)
            if kinds is None:
                return part_cache[group]
            key = (group,kinds)
            if key not in kind_cache:
                kind_cache[key] = tuple(op for op in part_cache[group] if op.kind in kinds)
            return kind_cache[key]
        def reference(op: Operation) -> OperationValue:
            return OperationValue(self.snapshot,op.id,op.kind.lower(),op.native_kind,owner.path,op.line,op.owner,owner.language,str(op.attrs.get('execution','unknown')))
        def declaration_group(start: int) -> str | None:
            candidates = [op for op in operations.values() if op.start <= start < op.end]
            op = min(candidates,key=lambda op:op.end-op.start) if candidates else None
            seen = set()
            while op is not None and op.id not in seen:
                seen.add(op.id)
                if successors(op.id):
                    return op.id
                op = operations.get(op.parent or '')
            return None
        def derived_from(source: QueryValue, origins: set[str]) -> QueryValue:
            """``argument $value from $place`` / ``return $value from $place``.

            The frontend publishes a dependence chain (``VALUE_DEPENDS_ON``) from an
            evaluated value to the inputs it consumes. The pattern states that the
            operand's own evaluated origin stands at the far end of that chain: the
            adapter converts its incoming parameter into the argument it delegates, or
            consumes the delegated result in the value it returns. Identity is not
            enough -- the retired ``walk`` clause required at least one hop -- so this
            only accepts a genuine derivation.
            """
            if isinstance(source, Unknown):
                return source
            if not isinstance(source, Node):
                return Unknown('derivation_source_unknown')
            if not origins:
                return Unknown('derivation_origin_missing')
            # The place may be the invoked callable itself rather than a storage: a value
            # that consumes a call *of* that callable stands at the same far end of the
            # chain, so the callee's own occurrences count as the derivation's source.
            occurrences = {f.subject for relation in ('TARGET','DECLARED_TARGET','MAY_TARGET')
                           for f in rows_to(relation, source.local_id)}
            frontier = set(origins)
            seen = set(frontier)
            unsure = False
            for _ in range(8):
                reached: set[str] = set()
                for node in frontier:
                    links = rows('VALUE_DEPENDS_ON', node)
                    # A call standing in the chain consumes its own operands, so the
                    # derivation continues through it: ``sink(str(request))`` derives from
                    # ``request`` one call further out.
                    links = list(links) + list(rows('ARGUMENT_VALUE_ORIGIN', node))
                    if any(f.attrs.get('modality') == 'may' for f in links):
                        unsure = True
                    reached |= {f.object for f in links}
                if source.local_id in reached or reached & occurrences:
                    return Unknown('derivation_may') if unsure else True
                frontier = reached - seen
                if not frontier:
                    return False
                seen |= reached
            return Unknown('derivation_depth_exceeded')

        def captured_reaches(value_id: str, targets: set[str]) -> QueryValue:
            """Compare evaluated origins; historical writes cannot prove a use."""
            if (value_id in targets or producers.get(value_id) in targets
                    or any(f.object == value_id for target in targets for f in rows('RESULT', target))):
                return True
            # A binding/loaded value is not an evaluated origin. Callers must
            # supply a snapshot or retain uncertainty instead of traversing
            # FLOWS_TO, which includes writes superseded before this occurrence.
            if any(t in ir.entities and ir.entities[t].kind in ('STORAGE','PARAMETER','MEMBER')
                   or rows('LOADED_FROM',t) for t in targets):
                return Unknown('value_provenance_incomplete')
            return False

        def member_place(expected: Expr | SourceExpr, op: Operation, current: dict[str,QueryValue],
                         candidates: set[str]) -> QueryValue:
            """Resolve ``$place.name`` to the member entity that occurrence touches.

            The member must belong to the place the pattern bound *and* be declared by
            a field role of the pattern with that name: the query names the member
            literally, and the pattern's roles say which declaration it must be.
            """
            object_role = current.get(expected.args[0].value) if expected.args else None
            if not isinstance(object_role,Node):
                return Unknown('member_object_unknown')
            if expected.value == '_':
                # ``$place._`` — a member of the bound place, at any depth: the
                # pattern claims the *path*, not the member's spelling. Nesting is a
                # chain of MEMBER_OF, so walk it upward from every candidate.
                for candidate in sorted(candidates):
                    reached = {candidate}
                    frontier = [candidate]
                    for _ in range(8):
                        parents = {f.object for node in frontier for f in rows('MEMBER_OF',node)}
                        if object_role.local_id in parents:
                            kinds = [f.object for f in rows('ENTITY',candidate)]
                            return value_node(candidate,kinds[0] if len(kinds)==1 else 'MEMBER')
                        frontier = [node for node in parents if node not in reached]
                        reached |= parents
                        if not frontier:
                            break
                return False
            if expected.value == '' and len(expected.args) == 2:
                # ``$place.$field``: the member the pattern's declaration role names.
                named = current.get(expected.args[1].value)
                if not isinstance(named,Node):
                    return Unknown('member_declaration_unknown')
                declared = {named.local_id}
            else:
                declared = {node.local_id for node in current.values()
                            if isinstance(node,Node) and node.name == expected.value}
            for candidate in sorted(candidates):
                if object_role.local_id not in {f.object for f in rows('MEMBER_OF',candidate)}:
                    continue
                declarations = {f.object for f in rows('MEMBER_DECLARATION',candidate)}
                if not declarations & declared:
                    continue
                kinds = [f.object for f in rows('ENTITY',candidate)]
                return value_node(candidate,kinds[0] if len(kinds) == 1 else 'MEMBER')
            return False

        def source_matches(expected: Expr | SourceExpr, actual: Operation, current: dict[str,QueryValue], resolved: set[str] | None = None) -> QueryValue:
            nonlocal boolean_results
            self.check()
            if expected.kind == 'call' and expected.value == 'read':
                return source_matches(expected.args[0].args[0],actual,current,resolved)
            if expected.kind == 'member':
                # A member *read*: the occurrence must reference that member of the bound
                # place, declared by the field role the pattern named.
                referenced = rows('BINDING_REFERENCE',actual.id) or rows('READ_ORIGIN',actual.id)
                if len(referenced) != 1:
                    return Unknown('member_reference_incomplete')
                return member_place(expected,actual,current,{referenced[0].object})
            if expected.kind == 'index':
                # ``if ($pool[$key] == null)``: the condition's subject is the *read* of a
                # bound place at a key. The access publishes the element it yielded as a
                # VALUE node carrying CONTAINER/INDEX -- the same evidence the landed
                # indexed reads and indexed calls answer with -- so the guard is the
                # element's own provenance, not the spelling the source used.
                container = current.get(expected.args[0].value)
                key = expected.args[1]
                key_node = current.get(key.value) if key.kind == 'role' else None
                if not isinstance(container,Node):
                    return Unknown('index_container_unknown')
                if key.kind == 'role' and not isinstance(key_node,Node):
                    return Unknown('index_key_unknown')
                elements = [f.object for f in rows('VALUE',actual.id)]
                elements += [entity.id for entity in ir.entities.values()
                             if entity.kind == 'VALUE'
                             and entity.attrs.get('start_byte') == actual.start
                             and entity.attrs.get('end_byte') == actual.end]
                for element in elements:
                    if not any(f.object == container.local_id for f in rows('CONTAINER',element)):
                        continue
                    if key.kind == 'wildcard':
                        return True
                    if isinstance(key_node,Node) and any(f.object == key_node.local_id
                                                         for f in rows('INDEX',element)):
                        return True
                    if key.kind == 'literal' and any(f.attrs.get('text') == json.loads(key.value)
                                                     for f in rows('INDEX',element)):
                        return True
                return False
            if expected.kind == 'wildcard':
                return True
            nested = children.get(actual.id,[])
            if actual.native_kind in ('parenthesized_expression','expression_statement','expression_list','condition_clause') and len(nested) == 1:
                return source_matches(expected,nested[0],current,resolved)
            if expected.kind == 'role':
                if expected.value not in current:
                    # BODY captures the value this occurrence denotes. The pattern
                    # declared the role's domain; the witness is the operand's own
                    # reference, so no global enumeration of values is needed.
                    referenced = rows('BINDING_REFERENCE',actual.id) or rows('VALUE_DEPENDENCE_ORIGIN',actual.id)
                    if len(referenced) == 1:
                        target_id = referenced[0].object
                        kinds = [f.object for f in rows('ENTITY',target_id)]
                        current[expected.value] = value_node(target_id,kinds[0] if len(kinds) == 1 else 'VALUE')
                        return True
                    if not referenced:
                        current[expected.value] = value_node(actual.id,'VALUE')
                        return True
                    return Unknown('value_capture_incomplete')
                node = current.get(expected.value,Unknown('binding_unknown'))
                if resolved is None:
                    references = rows('BINDING_REFERENCE',actual.id)
                    if references:
                        resolved = {f.object for f in references}
                captured = (node.local_id if isinstance(node,Node) and node.kind == 'VALUE'
                            else node if isinstance(node,str) else None)
                if captured is not None:
                    # A captured call result: the occurrence must carry that value's
                    # provenance. Without a modelled occurrence it is not this one.
                    origins = rows('READ_ORIGIN',actual.id)
                    if origins:
                        truth = captured_reaches(captured,{f.object for f in origins})
                        return Unknown('condition_origin_may') if truth is True and any(
                            f.attrs.get('modality') != 'must' for f in origins) else truth
                    if actual.kind == 'CALL':
                        occurrence=calls.get((actual.start,actual.end))
                        if occurrence is not None:
                            return captured_reaches(captured,{occurrence.id})
                    return captured_reaches(captured,resolved) if resolved else False
                if not isinstance(node,Node):
                    return Unknown('binding_unknown')
                if resolved is not None:
                    if node.local_id in resolved:
                        return True
                    # A **member read** of that place flows into it (``x = other.field``):
                    # the occurrence is a MEMBER, not the place entity itself.
                    return any('MEMBER' in {f.object for f in rows('ENTITY',value)}
                               and any(f.object == node.local_id for f in rows('FLOWS_TO',value))
                               for value in resolved)
                if actual.native_kind not in ('identifier','name'):
                    return False
                if actual.attrs.get('text') != node.name:
                    return False
                aliases = [n for n in local_nodes if n.name == node.name and n.kind in ('STORAGE','PARAMETER')]
                return True if len(aliases) == 1 and aliases[0].local_id == node.local_id else Unknown('binding_resolution_incomplete')
            if expected.kind == 'literal':
                text = actual.attrs.get('text')
                if not isinstance(text,str) or 'char' in actual.native_kind:
                    return False
                try:
                    parsed = {'true':True,'false':False,'null':None,'nil':None,'undefined':None}.get(text, ...)
                    if parsed is ...:
                        parsed = ast.literal_eval(text)
                    wanted = json.loads(expected.value)
                    return type(parsed) is type(wanted) and parsed == wanted
                except (ValueError,SyntaxError):
                    return False
            operators = rows('OPERATOR',actual.id)
            normalize = {'&&':'and','||':'or','!':'not'}
            actual_operator = normalize.get(operators[0].object,operators[0].object) if operators else None
            # A strict source comparison is narrower than the equality KQL states, so
            # ``===`` satisfies ``==`` and ``!==`` satisfies ``!=``. The reverse is not
            # true -- loose equality coerces -- and KQL has no strict test to ask for.
            if actual_operator is not None:
                actual_operator = {'===':'==','!==':'!='}.get(actual_operator,actual_operator)
            # Source null tests admit identity/strict spellings. Do not generalize
            # this to arbitrary equality: coercion and operator overloads differ.
            if actual_operator is not None and any(arg.kind == 'literal' and arg.value == 'null' for arg in expected.args):
                actual_operator = {'is':'==','is not':'!=','===':'==','!==':'!='}.get(actual_operator,actual_operator)
            # Equality to false is equivalent to logical negation only for a
            # primitive boolean result. Dynamic falsey values (None, 0, empty
            # containers) do not justify that rewrite.
            if (expected.kind == 'binary' and expected.value == '=='
                    and len(expected.args)==2 and expected.args[0].kind=='role'
                    and expected.args[1].kind=='literal' and expected.args[1].value=='false'
                    and actual_operator=='not'):
                operands=rows('OPERAND',actual.id)
                if len(operands)!=1 or operands[0].object not in operations:
                    return Unknown('operand_operation_missing')
                matched=source_matches(expected.args[0],operations[operands[0].object],current)
                if matched is False:return False
                captured=current.get(expected.args[0].value)
                producer=producers.get(captured.local_id) if isinstance(captured,Node) else None
                if producer is None and isinstance(captured,Node):
                    producer=next((f.subject for f in self.semantic.index.rows('RESULT')
                                   if f.object==captured.local_id),None) if hasattr(self.semantic,'index') else None
                from .boolean_results import BooleanResults
                index=getattr(self.semantic,'index',None)
                if boolean_results is None:
                    if index is None:
                        # Saved execution obtains facts from its immutable
                        # semantic snapshot and syntax from the same source unit.
                        from types import SimpleNamespace
                        full_unit=self.store.load_unit(owner.unit)
                        def boolean_rows(relation,subject=None):
                            if subject is not None:return self.semantic.facts(relation,subject)
                            return [fact for entity in full_unit.entities
                                    for fact in self.semantic.facts(relation,entity)]
                        index=SimpleNamespace(ir=full_unit,rows=boolean_rows)
                    boolean_results=BooleanResults(index,self.check)
                if producer is None or boolean_results is None or not boolean_results.is_boolean(producer):
                    return Unknown('boolean_result_unproven')
                return matched
            expected_operands = expected.args
            if expected.kind == 'call' and expected.value == 'binary':
                left,operator,right = binary_parts(expected)
                if actual_operator is None or not matches_operator(operator,actual_operator):
                    return False
                expected_operands = (left,right)
            elif actual_operator != expected.value:
                return False
            operands = sorted(rows('OPERAND',actual.id),key=lambda f:f.attrs.get('position',0))
            if len(operands) != len(expected_operands):
                return False
            truth = True
            for position,(e,f) in enumerate(zip(expected_operands,operands)):
                if f.object not in operations:
                    return Unknown('operand_operation_missing')
                def consumes_value(expression):
                    selected = current.get(expression.value) if expression.kind == 'role' else None
                    return (isinstance(selected,Node) and selected.kind == 'VALUE'
                            or any(consumes_value(arg) for arg in expression.args))
                origins = ([origin for value in resolved or ()
                            for origin in rows('VALUE_DEPENDS_ON',value)
                            if origin.attrs.get('position') == position
                            and origin.attrs.get('basis') == 'evaluated-expression-inputs/1']
                           if consumes_value(e) else [])
                matched = source_matches(e,operations[f.object],current,
                                         {origin.object for origin in origins} if origins else None)
                if matched is True and any(origin.attrs.get('modality') != 'must' for origin in origins):
                    matched = Unknown('expression_origin_may')
                truth = conjunction(truth,matched)
            return truth
        def value_node(value_id: str, kind: str = 'VALUE') -> Node:
            """A Node for a produced value or type: predicates compare Node identities."""
            return Node(0,owner.unit,value_id,kind,'',owner.local_id,
                        owner.line,owner.end_line,owner.path,owner.language)

        write_positions: dict[str,list[int]] = {}

        def iteration_value_at(value_id: str, binding: str, point: Operation) -> QueryValue:
            loop, original = self.iteration_values[value_id]
            if binding != original:
                return False
            status = rows('STORAGE_WRITE_STATUS',original)
            if not status or any(f.object != 'supported' for f in status):
                return Unknown('iteration_binding_writes_unknown')
            if original not in write_positions:
                positions = []
                # Include enclosing iteration regions: a nested BODY must see
                # an explicit replacement made before its own region begins.
                for candidate in ir.operations:
                    self.check()
                    if candidate.owner == owner.local_id and any(
                        f.object == original for relation in ('ASSIGNMENT_TARGET','ITERATION_BINDING')
                        for f in rows(relation,candidate.id)
                    ):
                        positions.append(candidate.start)
                write_positions[original] = sorted(positions)
            positions = write_positions[original]
            next_write = bisect_right(positions,loop.start)
            if next_write < len(positions) and positions[next_write] < point.start:
                return False
            return True

        def constructs(call, target) -> bool:
            """A constructor symbol requires resolved overload identity."""
            selected = {f.object for f in rows('CONSTRUCTOR_TARGET',call.id)}
            return selected == {target.local_id}

        def match_step(item: Clause, group: str, current: dict[str,QueryValue], cursor: str | None = None) -> Iterator[tuple[dict[str,QueryValue],bool,str]]:
            selection = operation_filter(item)
            candidates = parts(group,selection.kinds)
            # ``call $container[$key]`` is the element-origin callee. Only that clause
            # widens the candidates: the grammar may have filed the call under another
            # native kind (Go parses an indexed ``table[key](arg)`` as a type conversion),
            # while the semantic layer still publishes the call over the same byte span.
            foreign_callee_ids = foreign_call_ids if selection.semantic_calls else frozenset()
            if foreign_callee_ids:
                candidates = candidates + tuple(op for op in parts(group)
                                                if op.id in foreign_callee_ids)
            for op in candidates:
                if cursor is not None:
                    # Within one source statement, an operand completes before
                    # its enclosing operation. Do not guess sibling evaluation
                    # order (which differs across languages).
                    child = operations.get(cursor)
                    ancestors = set()
                    while child is not None and child.parent and child.parent not in ancestors:
                        ancestors.add(child.parent)
                        child = operations.get(child.parent)
                    if op.id not in ancestors:
                        # ``call alongside $x { ... }``: the pattern claims this
                        # occurrence is the sibling operand of the one just matched --
                        # both are operands of the same enclosing operation. That is
                        # the evidence; the walker still refuses to guess an order it
                        # was not told about.
                        if 'alongside' in item.flags and op.parent is not None and operations.get(op.parent) is not None \
                                and op.parent == operations[cursor].parent:
                            pass
                        else:
                            # A call the grammar filed under another native kind is a *child*
                            # of the statement the cursor anchors: it is inside that statement,
                            # so the operand-order rule has nothing to exclude.
                            inside = op.id in foreign_callee_ids
                            parent = operations.get(op.parent) if op.parent is not None else None
                            seen = {op.id}
                            while inside and parent is not None and parent.id not in seen:
                                if parent.id == cursor:
                                    break
                                seen.add(parent.id)
                                parent = operations.get(parent.parent) if parent.parent is not None else None
                            if not inside or parent is None or parent.id != cursor:
                                continue
                truth = False
                updated = dict(current)
                if item.kind == 'insert':
                    collection = current.get(item.role)
                    # Insertion facts hang off the *call occurrence*; a write-shaped
                    # insertion (``m[k] = v``) hangs off the operation. Ask both.
                    occurrence = calls.get((op.start,op.end))
                    subjects = [op.id] + ([occurrence.id] if occurrence is not None else [])
                    def inserted_rows(relation):
                        return [f for subject in subjects for f in rows(relation,subject)]
                    collections = ({f.object for f in inserted_rows('INSERTS_INTO')}
                                   | {f.object for f in inserted_rows('WRITES_ELEMENT')})
                    if not isinstance(collection,Node):
                        # A fresh role names the collection the insertion lands in: the
                        # write target binds it, as the walk binds the source of an
                        # unbound ``iterate $source as $item``. The insertion must name
                        # exactly one collection; a keyed bucket and its registry are
                        # two, so that spelling still requires a bound place.
                        options = set(collections)
                        for bucket in collections:
                            options |= {f.object for f in rows('CONTAINER',bucket)}
                        if len(options) != 1:
                            continue
                        collection = value_node(next(iter(options)),'STORAGE')
                        updated[item.role] = collection
                    if item.name:
                        # ``insert $handler into $table at $key writes: 1;``: the insertion
                        # is the only indexed write its owner performs on that collection,
                        # the count the write inventory publishes per write owner.
                        counts = rows('INDEXED_WRITE_COUNT',op.id)
                        if len(counts) != 1 or counts[0].object != item.name:
                            continue
                    key_verified = False
                    landed = landed_place(producers,self.semantic,collection)
                    if landed and landed in collections:
                        # The pattern named the local by the call it came from: the insertion
                        # fills the place that call's result landed in.
                        collection = value_node(landed,'STORAGE')
                    if collection.local_id not in collections:
                        # ``insert $x into $registry[$topic]`` lands in a *bucket* of the
                        # registry: the insertion names that bucket, so accept it when the
                        # bucket's container is the registry and the key matches.
                        matched = False
                        for bucket in collections:
                            if not any(f.object == collection.local_id for f in rows('CONTAINER',bucket)):
                                continue
                            if len(item.expressions) > 1:
                                key = (current.get(item.expressions[1].value)
                                       if item.expressions[1].kind == 'role' else None)
                                if (not isinstance(key,Node)
                                        or not any(f.object == key.local_id for f in rows('INDEX',bucket))):
                                    continue
                            matched = True
                            key_verified = len(item.expressions) > 1
                            break
                        if not matched:
                            continue
                    # An API insertion publishes ``INSERTED_VALUE``; an indexed write
                    # publishes the stored value and the element write instead.
                    values = {f.object for f in inserted_rows('INSERTED_VALUE')}
                    inserted = (values
                                | {f.object for f in inserted_rows('STORES_VALUE')}
                                | {f.object for f in inserted_rows('ASSIGNMENT_VALUE')})
                    # ``INSERTED_INPUT`` is published only while the value reaching the
                    # collection still is the input the caller supplied. Rebinding that
                    # input (``task = None; queue.append(task)``) keeps the value fact but
                    # drops the input relation, so requiring it when it exists tells an
                    # insertion *of the input* from an insertion of something else. The
                    # widening below stays for the languages that never publish it.
                    inputs = {f.object for f in inserted_rows('INSERTED_INPUT')}
                    if inputs:
                        inserted &= inputs
                    # The operand names the value the insertion *carries*, not only the
                    # node stored verbatim: a language that first binds the value to a
                    # local name (``const action = ...; queue.push(action)``) or wraps it
                    # in a one-argument constructor (``queue.push(Box::new(action))``)
                    # still enqueues that same value, and ``insert $action into $queue``
                    # is how the pattern says so. Follow the binding (``ASSIGNED_FROM``),
                    # the wrapper's argument place (``ARGUMENT``) and the value that flows
                    # into the stored node (``FLOWS_TO``), to a bounded depth.
                    carried = set(inserted)
                    frontier = sorted(inserted)
                    for _ in range(3):
                        self.check()
                        following = {f.object for node in frontier
                                     for relation in ('ASSIGNED_FROM','FLOWS_TO','ARGUMENT')
                                     for f in self.semantic.facts(relation,node)}
                        following -= carried
                        if not following:
                            break
                        carried |= following
                        frontier = sorted(following)
                    truth = source_matches(item.expressions[0],op,updated,carried or None)
                    if truth is False and item.expressions[0].kind == 'role':
                        # The operand names the local by the call that filled it
                        # (``let $batch = call $lookup { ... }``); the frontend records the
                        # insertion against the place that call landed in. Resolve the one to
                        # the other, as ``landed_place`` does for a collection, provided the
                        # place keeps what the call left there: every other producer of the
                        # place must be the null-coalescing fallback collection
                        # (``if batch == null: batch = []``), never a second stored value.
                        operand = current.get(item.expressions[0].value)
                        landing = (landed_place(producers,self.semantic,operand)
                                   if isinstance(operand,Node) else '')
                        if isinstance(operand,Node) and landing and landing in (values
                                                   | {f.object for f in inserted_rows('ARGUMENT')}):
                            producer = producers.get(operand.local_id)
                            other = {f.object for f in rows('ASSIGNED_FROM',landing)
                                     if f.object != producer}
                            # The fallback writes a *fresh* collection (an empty literal or a
                            # constructor call), which is the only other write that leaves the
                            # call's own result in the place on the path that reads it.
                            if all('/COLLECTION:' in place
                                   or rows('ALLOCATES_TYPE',place)
                                   or any(f.attrs.get('construction') for f in rows('ENTITY',place))
                                   for place in other):
                                truth = True
                    # A keyed write publishes the element write instead of an API insertion,
                    # so the guard below belongs to the plain insertion only.
                    if truth is not False and not inputs and values and len(item.expressions) == 1:
                        # ``INSERTED_INPUT`` is published while the inserted value still is
                        # the input the caller supplied; the semantic layer drops it once
                        # that input is written (``task = None; tasks.append(task)``).
                        # Without it, an operand that *is* an input place therefore carries
                        # something else: the widening above exists for the alias and
                        # wrapper shapes, not for a rebound input.
                        operand = current.get(item.expressions[0].value)
                        declared = isinstance(operand,Node) and (
                            operand.kind == 'PARAMETER'
                            or any(f.object == 'PARAMETER'
                                   for f in rows('ENTITY',operand.local_id)))
                        if declared:
                            truth = False
                    if truth is not False and len(item.expressions) > 1 and not key_verified:
                        # A direct insertion into a keyed collection carries the index on
                        # the occurrence; the bucket branch already checked its bucket.
                        keys = {f.object for f in inserted_rows('INDEX')}
                        truth = conjunction(truth,source_matches(item.expressions[1],op,updated,keys or None))
                elif item.kind == 'clear':
                    # ``clear $collection after $iteration`` reads the lifecycle facts the
                    # structural IR publishes: the operation empties that collection, and it
                    # happens after the walk the pattern bound. The reset may be spelled as
                    # an assignment of an empty literal -- published on the statement -- or
                    # as an API invocation such as ``tasks.clear()``, which the semantic
                    # layer publishes on the call occurrence the statement performs.
                    cleared = current.get(item.role)
                    if not isinstance(cleared,Node):
                        continue
                    reset = calls.get((op.start,op.end)) if op.kind == 'CALL' else None
                    subjects = (op.id,reset.id) if reset is not None else (op.id,)
                    if not any(f.object == cleared.local_id
                               for subject in subjects for f in rows('CLEARS_COLLECTION',subject)):
                        continue
                    if item.name:
                        loop = current.get(item.name)
                        if not isinstance(loop,Node):
                            continue
                        if not any(f.object == loop.local_id
                                   for subject in subjects for f in rows('AFTER_ITERATION',subject)):
                            continue
                    truth = True
                elif item.kind == 'if' and op.kind == 'BRANCH':
                    tests = rows('CONTROL_CONDITION',op.id)
                    if len(tests) != 1 or tests[0].object not in operations:
                        continue
                    truth = source_matches(item.expressions[0],operations[tests[0].object],updated)
                    expected = item.expressions[0]
                    if expected.kind == 'binary' and expected.value in ('==','!='):
                        left,right = expected.args
                        if right.kind == 'literal' and right.value == 'null' and left.kind == 'role':
                            binding = current.get(left.value)
                            if isinstance(binding,Node) and binding.kind != 'VALUE':
                                null_tests = [f for f in rows('NULL_TEST',op.id) + rows('UNDEFINED_TEST',op.id) if f.object == binding.local_id]
                                if null_tests:
                                    truth = any(f.attrs.get('when') in ((True,'true') if expected.value == '==' else (False,'false')) for f in null_tests)

                    if truth is False:
                        continue
                    witnesses=[(updated,is_unknown(truth))]
                    for position, arm_pattern in enumerate(control_patterns[item]):
                        role = 'consequence' if position == 0 else 'alternative'
                        regions = [child for child in children.get(op.id,()) if child.role == role]
                        next_witnesses=[]
                        for witness, prior_unknown in witnesses:
                            for arm_region in regions:
                                for arm_result,uncertain in self.match(arm_pattern,witness,region=arm_region,linear_arm=pattern.linear):
                                    result=dict(witness)
                                    for name in arm_pattern.outputs:
                                        if name in pattern.outputs:result[name]=arm_result[name]
                                    next_witnesses.append((result,prior_unknown or uncertain))
                        witnesses=next_witnesses
                        if not witnesses:break
                    for result,uncertain in witnesses:
                        if item.alias:
                            # ``if (...) as $branch { ... }``: the pattern names the
                            # branch occurrence the condition opens.
                            result = {**result, item.alias: reference(op)}
                        yield result,uncertain,op.id
                    continue
                if item.kind == 'macro':
                    selected=current.get(item.role)
                    if isinstance(selected,Node) and selected.local_id == op.id and op.native_kind == 'macro_invocation':
                        yield dict(current),False,op.id
                    continue
                if item.kind == 'iterate' and 'keys' in item.flags and op.kind == 'LOOP':
                    # ``iterate keys of $registry`` is the keyed walk: the callable-level
                    # fact says the collection's keys are what gets invoked.
                    keyed = current.get(item.expressions[0].value)
                    if not isinstance(keys_target := keyed,Node):
                        continue
                    if not any(f.object == keys_target.local_id
                               for f in self.semantic.facts('ITERATES_KEYS_CALLS',owner.local_id)):
                        continue
                if item.kind == 'iterate' and op.kind == 'LOOP':
                    expected_source = item.expressions[0]
                    if expected_source.kind == 'index':
                        # ``iterate $registry[$topic] as $item`` walks the bucket that
                        # key selects: the container is the bound place, the key its index.
                        collection = current.get(expected_source.args[0].value)
                        loop_key = (current.get(expected_source.args[1].value)
                                    if expected_source.args[1].kind == 'role' else None)
                    else:
                        collection, loop_key = current.get(expected_source.value), None
                    unbound_source = not isinstance(collection,Node)
                    if unbound_source and expected_source.kind != 'role':
                        continue
                    constraints=[c for c in item.blocks[0] if c.kind=='property']
                    if any(bool(op.attrs.get('async')) != (c.expressions[0].value=='true')
                           for c in constraints if c.name == 'async'):
                        continue
                    body_constraint=next((c for c in constraints if c.name=='body'),None)
                    keys_iteration = 'keys' in item.flags
                    copy_iteration = 'copy' in item.flags
                    sources={f.object for f in rows('ITERATION_SOURCE',op.id)}
                    accessed: set[str] = set()
                    if isinstance(collection,Node) and expected_source.kind != 'index':
                        # ``iterate $place`` claims the *place* the walk reads, and a walk
                        # may reach it through an access: a borrow or an ``iter()``/getter
                        # call whose receiver is the place. The access is an IR detail, so
                        # the pattern does not have to spell it. An indexed walk
                        # (``iterate $registry[$topic]``) states a key as well, which the
                        # access would bypass, so it stays exact.
                        accessed = {source for source in sources
                                    if source != collection.local_id
                                    and any(f.object == collection.local_id
                                            for f in rows('RECEIVER',source))}
                        if accessed:
                            sources = accessed
                    if unbound_source:
                        # The clause itself names the walked collection, so bind the one
                        # place the loop reads as the role's entity reference.
                        if len(sources) != 1:
                            continue
                        collection = value_node(next(iter(sources)),'STORAGE')
                    assert isinstance(collection,Node)
                    if copy_iteration:
                        # The walk runs over a snapshot the source took of the place:
                        # ``ITERATION_SNAPSHOT`` names the copy call and
                        # ``COLLECTION_SNAPSHOT_OF`` says which place that call copies.
                        # The walked source is the copy itself or a local alias of it,
                        # so a walk of the place itself is not a snapshot and does not
                        # satisfy the clause.
                        copies = {f.object for f in rows('ITERATION_SNAPSHOT',op.id)}
                        snapshots = {copy for copy in copies
                                     if any(f.object == collection.local_id
                                            for f in rows('COLLECTION_SNAPSHOT_OF',copy))}
                        # The walked source is the copy or an alias of it, and an alias
                        # may itself have been aliased again, so follow the assignments
                        # that take their value from the copy before deciding.
                        derived = set(snapshots)
                        for _ in range(4):
                            reached = {f.subject for node in derived
                                       for f in rows_to('ASSIGNED_FROM',node)} - derived
                            if not reached:
                                break
                            derived |= reached
                        sources = {source for source in sources if source in derived}
                        if not sources:
                            continue
                    # ``origin: $lookup;`` names the call whose result the walk reads: the
                    # pattern states the provenance the entry-source analysis would infer, so
                    # a local batch a lookup filled is walkable without an entry source.
                    origin = next((c for c in constraints if c.name == 'origin'), None)
                    if origin is not None:
                        origin_value = current.get(origin.expressions[0].value)
                        if not isinstance(origin_value,Node) or origin_value.local_id not in {
                                f.object for f in rows('ITERATION_ORIGIN',op.id)}:
                            continue
                        if len(sources) != 1:
                            continue
                        if (collection.kind == 'VALUE' and producers.get(
                                collection.local_id,collection.local_id) != origin_value.local_id):
                            continue
                        collection = value_node(next(iter(sources)),'STORAGE')
                        source_id = collection.local_id
                    else:
                        source_id=(next(iter(sources)) if (copy_iteration or accessed) and len(sources) == 1 else
                                   producers.get(collection.local_id,collection.local_id) if collection.kind=='VALUE' else collection.local_id)
                    # The entry-source analysis follows the *place* a walk reads. A walk
                    # over a call result has no place to track (``for await (const x of
                    # produce())``), so it has no entry source either and keeps the source
                    # test alone. A walk over a storage place publishes its entry source
                    # while the collection was neither replaced nor emptied before the
                    # loop, so a drain that starts after its own reset walks something else
                    # than what the registration filled.
                    entry_sources={f.object for f in rows('ITERATION_ENTRY_SOURCE',op.id)}
                    walked = any(f.object == 'STORAGE' for f in rows('ENTITY',source_id))
                    if (origin is None and not copy_iteration and walked and expected_source.kind != 'index'
                            and source_id not in entry_sources):
                        continue
                    if source_id not in sources:
                        # The walked collection may be a bucket of the bound place.
                        bucket = next((candidate for candidate in sources
                                       if any(f.object == collection.local_id for f in rows('CONTAINER',candidate))
                                       and (loop_key is None
                                            or not isinstance(loop_key,Node)
                                            or any(f.object == loop_key.local_id for f in rows('INDEX',candidate)))),None)
                        if bucket is None:
                            continue
                        source_id = bucket
                    for element in rows('ITERATION_BINDING',op.id):
                        # A keyed walk hands over what the map is keyed by; a value walk
                        # hands over its values. A plain iterable hands over its elements.
                        element_role = element.attrs.get('role')
                        if keys_iteration and element_role not in ('first','key'):
                            continue
                        if not keys_iteration and element_role != 'value':
                            continue
                        binding = next((n for n in local_nodes if n.local_id == element.object),None)
                        if binding is None:
                            continue
                        for body in rows('ITERATION_BODY',op.id):
                            body_region = operations.get(body.object)
                            if body_region is None:
                                continue
                            value_id = op.id+'/iteration-value/'+element.object
                            self.iteration_values[value_id] = (op,element.object)
                            if keys_iteration:
                                self.keyed_iterations.add(op.id)
                            value = value_node(value_id)
                            nested_inputs={**current,item.role:value}
                            if item.alias:nested_inputs[item.alias]=reference(op)
                            for nested_result, uncertain in self.match(nested_patterns[item],nested_inputs,region=body_region):
                                result = dict(current)
                                if item.alias:result[item.alias]=reference(op)
                                if body_constraint is not None:
                                    # The named body role is the walk's body region: the
                                    # loop body operation, so the pattern can pass it on.
                                    result[body_constraint.expressions[0].value]=reference(body_region)
                                if unbound_source:
                                    result[expected_source.value]=collection
                                if item.role in pattern.outputs:
                                    result[item.role]=binding
                                for name in nested_patterns[item].outputs:
                                    if name in pattern.outputs:result[name]=nested_result[name]
                                yield result,uncertain,op.id
                    continue
                clause = item.blocks[0][0] if item.kind == 'let' and item.blocks else item
                if clause.kind == 'construct' and op.kind == 'CALL':
                    # A source construction: accredited by the type it produces, not
                    # by a callable symbol (Go/Rust literals have none).
                    call = calls.get((op.start,op.end))
                    built = current.get(clause.role)
                    if call is None:
                        truth = Unknown('construct_resolution_missing')
                    else:
                        produced = {f.object for f in rows('RESULT',call.id)}
                        allocated = {f.object for f in rows('ALLOCATES_TYPE',call.id)}
                        instance = {f.object for value in produced for f in rows('INSTANCE_OF',value)}
                        if not isinstance(built,Node):
                            # Bind the constructed type; several distinct types are
                            # incomplete evidence, not a negative, and the role stays
                            # bound so projection never crashes.
                            types = allocated | instance
                            if len(types) == 1:
                                built = value_node(next(iter(types)),'CLASS')
                            else:
                                built = Unknown('construct_type_incomplete')
                                truth = Unknown('construct_type_incomplete')
                            updated[clause.role] = built
                        if isinstance(built,Node):
                            carried = built.local_id in instance
                            truth = True if built.local_id in allocated or carried else False
                        for constraint in clause.blocks[0]:
                            if constraint.kind == 'argument':
                                # ``argument $place at N;``: the value the construction
                                # was invoked with. The occurrence publishes ``ARGUMENT``
                                # rows, each carrying the position the constructor symbol
                                # received it at, so the clause can constrain both the
                                # value and where it stood (``new Idle(this)``).
                                expected = next((e for e in constraint.expressions
                                                 if e.kind != 'from'),None)
                                derivation = next((e for e in constraint.expressions
                                                   if e.kind == 'from'),None)
                                position = constraint.name
                                bound = (current.get(derivation.value) if derivation is not None
                                         else (current.get(expected.value)
                                               if expected is not None and expected.kind == 'role' else None))
                                if not isinstance(bound,Node):
                                    truth = conjunction(truth,Unknown('construct_argument_unknown'))
                                    continue
                                parameter_positions=set()
                                if constraint.role:
                                    parameter = current.get(constraint.role)
                                    if isinstance(parameter,Node):
                                        for binding in rows('CALL_BINDING',call.id):
                                            if any(f.object == parameter.local_id
                                                   for f in rows('BINDING_PARAMETER',binding.object)):
                                                parameter_positions.add(binding.attrs.get('position'))
                                matched = False
                                for argument in rows('ARGUMENT',call.id):
                                    if str(argument.attrs.get('kind','')).startswith('spread'):
                                        matched = disjunction(matched,Unknown('argument_pack_unresolved'))
                                        continue
                                    selected = (argument.attrs.get('position') in parameter_positions
                                                if constraint.role else
                                                (position == 'any'
                                                 or position.isdigit()
                                                 and argument.attrs.get('kind') == 'positional'
                                                 and argument.attrs.get('position') == int(position)))
                                    if not selected:
                                        continue
                                    candidate = argument.object == bound.local_id
                                    if candidate is False and bound.kind == 'CALL':
                                        # The operand is a construction, so an argument whose
                                        # value is that construction's result carries the
                                        # created value (``install(new Ready())``).
                                        results = {f.object for f in rows('RESULT',bound.local_id)}
                                        candidate = bool(results) and any(
                                            f.object in results for f in rows('VALUE',argument.object))
                                    matched = disjunction(matched,candidate)
                                truth = conjunction(truth,matched)
                                continue
                            if constraint.kind == 'property' and constraint.name == 'retained':
                                # ``retained: $gap;``: the conditional's other arm hands
                                # the gap back, so the construction is the arm the null
                                # test takes when the value is missing. The condition
                                # publishes NULL_TEST over the arm polarity it read and
                                # VALUE over each arm's operand.
                                previous = current.get(constraint.expressions[0].value)
                                if not isinstance(previous,Node):
                                    truth = conjunction(truth,Unknown('retained_binding_unknown'))
                                    continue
                                holds: QueryValue = False
                                for choice in {f.object for f in rows('BODY_VALUE',owner.local_id)}:
                                    for condition in {f.object for f in rows('SYNTAX_NODE',choice)}:
                                        for test in rows('NULL_TEST',condition):
                                            if test.object != previous.local_id:
                                                continue
                                            taken = 'BRANCH_TRUE' if test.attrs.get('when') == 'true' else 'BRANCH_FALSE'
                                            kept = 'BRANCH_FALSE' if test.attrs.get('when') == 'true' else 'BRANCH_TRUE'
                                            if call is None:
                                                continue
                                            holds_construction = any(
                                                call.id in {f.object for f in rows('VALUE',arm)}
                                                for arm in (f.object for f in rows(taken,condition)))
                                            retains = any(
                                                previous.local_id in {f.object for f in rows('VALUE',arm)}
                                                for arm in (f.object for f in rows(kept,condition)))
                                            holds = disjunction(holds,holds_construction and retains)
                                truth = conjunction(truth,holds)
                                continue
                            if constraint.kind != 'initializer':
                                continue
                            place = current.get(constraint.role)
                            if not isinstance(place,Node):
                                truth = conjunction(truth,Unknown('initializer_binding_unknown'))
                                continue
                            if constraint.expressions:
                                # ``initializer $field from $value;``: a keyed literal
                                # stores a named value in the field it initializes. Both
                                # claims are evidence -- the field is what the literal
                                # fills, the value is what the pattern bound (here the
                                # closure that captures the binding).
                                carried = current.get(constraint.expressions[0].value)
                                if not isinstance(carried,Node):
                                    truth = conjunction(truth,Unknown('initializer_value_unknown'))
                                    continue
                                # A construction publishes ``STORES_VALUE`` over its
                                # occurrence, while a role bound to its result names the
                                # synthesized result value: the producer links the two.
                                stored_ids = {carried.local_id, producers.get(carried.local_id)}
                                accepted = any(
                                    any(f.object == place.local_id for f in rows('INITIALIZES_FIELD',initializer.object))
                                    and any(f.object in stored_ids for f in rows('STORES_VALUE',initializer.object))
                                    for initializer in rows('HAS_INITIALIZER',call.id))
                                truth = conjunction(truth,accepted)
                                continue
                            stored = any(any(f.object == place.local_id for f in rows('STORES_VALUE',initializer.object))
                                         for initializer in rows('HAS_INITIALIZER',call.id))
                            # BODY reads the raw argument occurrence, so the carried
                            # place is the argument itself when it is passed directly.
                            loaded = any(f.object == place.local_id for f in rows('ARGUMENT',call.id))
                            forms = ({a.value for a in constraint.blocks[0][0].expressions[0].args}
                                     if constraint.blocks and constraint.blocks[0] else {'identity'})
                            accepted = 'identity' in forms and (stored or loaded)
                            if 'shallow_copy' in forms:
                                inputs = {f.object for f in rows('ARGUMENT',call.id)}
                                inputs.update(f.object for item in rows('HAS_INITIALIZER',call.id)
                                              for f in rows('STORES_VALUE',item.object))
                                accepted |= any(f.object == place.local_id for value in inputs
                                                for f in rows('SHALLOW_COPY_SOURCE',value))
                            truth = conjunction(truth,accepted)
                        if item.kind == 'let' and truth is not False:
                            updated[item.role] = value_node(next(iter(produced))) if len(produced) == 1 \
                                else Unknown('construct_result_incomplete')
                            truth = conjunction(truth,updated[item.role]) if len(produced) != 1 else truth
                            if len(produced) == 1:
                                captured = updated[item.role]
                                assert isinstance(captured,Node)
                                producers[captured.local_id] = call.id
                if clause.kind == 'call' and (op.kind == 'CALL' or op.id in foreign_callee_ids):
                    call = calls.get((op.start,op.end))
                    target = current.get(clause.role)
                    if clause.role not in current:
                        targets = ({f.object for relation in ('TARGET','DECLARED_TARGET')
                                    for f in rows(relation,call.id)} if call is not None else set())
                        if len(targets) == 1:
                            target_id = next(iter(targets))
                            metadata = rows('ENTITY',target_id)
                            name = next((f.attrs.get('name','') for f in metadata if f.object == 'CALLABLE'),'')
                            target = Node(0,owner.unit,target_id,'CALLABLE',name,None,
                                          owner.line,owner.end_line,owner.path,owner.language)
                        elif call is not None and any(
                                constraint.kind == 'argument'
                                or constraint.kind == 'property' and constraint.name == 'resolution'
                                for constraint in clause.blocks[0]):
                            # ``resolution: ...;`` is a statement about the occurrence, and
                            # ``argument ...;`` names what the call receives: either is
                            # evidence about the occurrence itself, so an occurrence no
                            # callable accredits still binds -- the call is what the clause
                            # asked about and its arguments carry the claim.
                            target = Node(0,owner.unit,call.id,'CALL',call.name or '',None,
                                          owner.line,owner.end_line,owner.path,owner.language)
                        else:
                            target = Unknown('call_target_incomplete')
                        updated[clause.role] = target
                    if clause.expressions and clause.expressions[0].kind == 'index':
                        # ``call $table[$key] { ... }``: the invoked value is an element of
                        # the bound container that key selects. The element's own
                        # CONTAINER/INDEX facts are the evidence, exactly as they are for an
                        # argument origin; the container stays the bound role.
                        operand = clause.expressions[0]
                        container = current.get(operand.args[0].value)
                        key = operand.args[1]
                        key_node = current.get(key.value) if key.kind == 'role' else None
                        truth = Unknown('callee_container_unknown')
                        if isinstance(container,Node):
                            truth = False
                            subjects = [op.id] + ([call.id] if call is not None else [])
                            elements = {f.object for subject in subjects
                                        for f in rows('CALLEE_VALUE',subject)}
                            if not elements:
                                # An indexed call may publish ``CALLEE_VALUE`` under the call
                                # occurrence that spans the same bytes as the operation rather
                                # than under the operation node itself.
                                index = getattr(self.semantic, 'index', None)
                                callee_facts = (index.rows('CALLEE_VALUE') if index is not None else
                                                (fact for entity_id in ir.entities
                                                 for fact in rows('CALLEE_VALUE', entity_id)))
                                elements = {f.object
                                            for f in callee_facts
                                            if (entity := ir.entities.get(f.subject)) is not None
                                            and entity.attrs.get('start_byte') == op.start
                                            and entity.attrs.get('end_byte') == op.end}
                            for element in elements:
                                if not any(f.object == container.local_id
                                           for f in rows('CONTAINER',element)):
                                    continue
                                if key.kind == 'wildcard':
                                    truth = True
                                elif isinstance(key_node,Node):
                                    truth = any(f.object == key_node.local_id
                                                for f in rows('INDEX',element))
                                elif key.kind == 'literal':
                                    truth = any(f.attrs.get('text') == json.loads(key.value)
                                                for f in rows('INDEX',element))
                                else:
                                    truth = any(True for _ in rows('INDEX',element))
                                if truth:
                                    break
                        if truth is False:
                            continue
                        target = None
                    if 'qualify' in item.flags:
                        # ``call qualify $parameter { ... }``: the declaration's own
                        # generic parameter selects the invoked operation (C++
                        # ``P::operation``). Nothing is stored, so the evidence is the
                        # lexical qualifier the frontend accredited to this declaration:
                        # ``TYPE_PARAMETER_RECEIVER(call, name)`` names the parameter and
                        # ``TYPE_PARAMETER_OWNER(call, declaration)`` ties it to the
                        # declaring unit, so homonymous parameters of other scopes do not
                        # contribute evidence.
                        unit = current.get('unit') or current.get('$unit')
                        place = current.get(item.role)
                        qualifiers = ({f.object for f in rows('TYPE_PARAMETER_RECEIVER',call.id)}
                                      if call is not None else set())
                        owners = ({f.object for f in rows('TYPE_PARAMETER_OWNER',call.id)}
                                  if call is not None else set())
                        bound = place.local_id if isinstance(place,Node) else place
                        truth = bool(qualifiers) and isinstance(unit,Node) and any(
                            str(name) == str(bound) for name in qualifiers) and unit.local_id in owners
                        if truth is False:
                            continue
                        target = None
                    if 'on' in item.flags:
                        # ``call on $item { ... }``: the receiver is the evidence, the
                        # invoked operation is whatever the element offers.
                        place = current.get(item.role)
                        receivers = {f.object for f in rows('RECEIVER',call.id)} if call is not None else set()
                        if isinstance(place,Node) and place.local_id in self.iteration_values:
                            # The iterated element is the receiver: the loop binding is
                            # the element's identity here, exactly as it is in callee
                            # position below. The loop must also be the walk that invokes
                            # this call -- ``ITERATION_INVOKES_VALUE`` is published only
                            # while the binding still names the element at this
                            # occurrence, so a loop variable rebound before the call does
                            # not count as invoking the element.
                            loop, element_id = self.iteration_values[place.local_id]
                            if element_id not in receivers:
                                truth = (False if receivers
                                                     else Unknown('call_receiver_missing'))
                            elif call is not None and not any(
                                    f.object == call.id
                                    for f in rows('ITERATION_INVOKES_VALUE',loop.id)):
                                truth = False
                            else:
                                truth = True
                        else:
                            truth = (place.local_id in receivers if isinstance(place,Node) and receivers
                                     else Unknown('call_receiver_missing') if isinstance(place,Node)
                                     else Unknown('call_receiver_binding_unknown'))
                        if truth is False:
                            continue
                        arguments = rows('ARGUMENT',call.id) if call is not None else []
                        # The receiver is the evidence; there is no named callee to
                        # resolve, so the target-matching branch below must not run.
                        target = None
                    elif call is not None and isinstance(target,Node) and target.kind not in ('CALLABLE',):
                        # A selected Call is an occurrence, while a binding can
                        # retain a callable. Neither requires inventing a target
                        # declaration for an external or dynamic invocation.
                        truth = (call.id == target.local_id if target.kind == 'CALL' else
                                 any(f.object == target.local_id for f in rows('CALLEE_VALUE',call.id)))
                        if not truth and target.kind != 'CALL':
                            # ``let $adapted = call $adapter { ... }`` retains the *result* of
                            # that call, so invoking the retained value is the frontend's
                            # ``INVOKES_RESULT_OF`` (``f(x)(y)``): the invocation accredits the
                            # call that produced the place, not a callable declaration.
                            producer = producers.get(target.local_id)
                            truth = (any(f.object == producer for f in rows('INVOKES_RESULT_OF',call.id))
                                     if producer is not None else False)
                        if truth is not True and target.local_id in self.iteration_values:
                            # The iterated element is what the walk invokes: the collection
                            # supplies the callable (``item(value)``), so ``CALLEE_VALUE``
                            # is the evidence. The element being the *receiver* of the
                            # invocation (``item.next(value)``) is a different claim, spelled
                            # ``call on $item`` and matched by the branch above; a receiver
                            # call must not satisfy callee position, or the two spellings
                            # would be indistinguishable.
                            loop, element_id = self.iteration_values[target.local_id]
                            truth = any(f.object == element_id for f in rows('CALLEE_VALUE',call.id))
                        target = None
                    if call is None or (target is not None and not isinstance(target,Node)):
                        truth = Unknown('call_resolution_missing')
                    elif target is not None:
                        # ``DECLARED_TARGET`` is a nominally accredited slot, so it
                        # counts as an exact target; ``MAY_TARGET`` only as possible.
                        exact = ({f.object for f in rows('TARGET',call.id)}
                                 | {f.object for f in rows('DECLARED_TARGET',call.id)})
                        possible = exact | {f.object for f in rows('MAY_TARGET',call.id)}
                        mode = next((c.expressions[0].value.strip('"') for c in clause.blocks[0] if c.kind == 'property' and c.name == 'dispatch'), 'exact')
                        if mode in ('possible','contract'):
                            # A typed traversal accredits the operation on the
                            # element's contract even when the frontend cannot
                            # resolve the temporary iteration variable itself.
                            receiver_role = next((c.expressions[0].value for c in clause.blocks[0]
                                if c.kind == 'property' and c.name == 'receiver'),None)
                            receiver = current.get(receiver_role) if receiver_role is not None else None
                            if isinstance(receiver,Node) and receiver.local_id in self.iteration_values:
                                loop,_ = self.iteration_values[receiver.local_id]
                                # A keyed walk hands over the key type and a value walk the
                                # value type; a plain iterable hands over its element type.
                                typed = ('KEY_TYPE' if loop.id in self.keyed_iterations else 'VALUE_TYPE')
                                for source in rows('ITERATION_SOURCE',loop.id):
                                    for element in [*rows(typed,source.object), *rows('ELEMENT_TYPE',source.object)]:
                                        for method in rows('HAS_METHOD',element.object):
                                            if method.object == target.local_id and target.name == call.name:
                                                possible.add(method.object)
                                            elif (mode == 'contract' and target.name == call.name
                                                  and any(f.object == method.object
                                                          for f in rows('OVERRIDES',target.local_id))):
                                                # ``dispatch: contract;`` -- the element's contract
                                                # declares the member the pattern's callable
                                                # *replaces*. The dispatched target is the
                                                # overriding one, so the base declaration accredits
                                                # the same occurrence: a composite walks the
                                                # contract and calls the concrete operation that
                                                # overrides it.
                                                possible.add(target.local_id)
                                    if (mode == 'contract' and target.name == call.name
                                            and any(f.object == source.object
                                                    for f in rows('ITERATED_CALL',call.id))):
                                        # ``dispatch: contract;`` -- the frontend accredits this
                                        # occurrence as the invocation the *walk* performs on the
                                        # element, so a collection whose element type was never
                                        # published still names the operation the walk dispatches
                                        # to, and the pattern still claims the same-named call.
                                        possible.add(target.local_id)
                        if mode in ('possible','contract'):
                            truth = (target.local_id in possible if possible
                                     else Unknown('call_target_incomplete'))
                        elif target.local_id in exact and len(exact) == 1:
                            truth = True
                        elif target.local_id in exact:
                            # Several accredited targets: this callable is one of them.
                            truth = Unknown('call_target_incomplete')
                        elif constructs(call,target):
                            truth = True
                        else:
                            # The accredited targets are other callables, or no
                            # resolution evidence exists for this occurrence.
                            truth = False
                    if call is not None and truth is not False:
                        arguments = rows('ARGUMENT',call.id)
                        for constraint in clause.blocks[0]:
                            if constraint.kind == 'property' and constraint.name == 'entry':
                                # ``entry: $place;`` is the binding the occurrence is entered
                                # with, published as CALL_ENTRY_BINDING(occurrence, place).
                                place = current.get(constraint.expressions[0].value)
                                entries = {f.object for f in rows('CALL_ENTRY_BINDING',call.id)}
                                truth = conjunction(truth,(place.local_id in entries
                                                           if isinstance(place,Node)
                                                           else Unknown('call_entry_binding_unknown')))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'receiver':
                                place = current.get(constraint.expressions[0].value)
                                receivers = {f.object for f in rows('RECEIVER',call.id)}
                                if constraint.expressions[0].kind == 'member':
                                    # ``receiver: $holder._;`` — this occurrence is dispatched
                                    # on a member of a bound place. Some frontends accredit
                                    # that member as the callee *value* rather than as the
                                    # receiver relation (Rust ``self.field.clone()``), so the
                                    # member is resolved against the callee-value candidates.
                                    resolved = member_place(constraint.expressions[0],op,current,
                                                            {f.object for f in rows('CALLEE_VALUE',call.id)})
                                    if resolved is False:
                                        present = False
                                    elif isinstance(resolved,Node):
                                        present = True
                                    else:
                                        present = Unknown('call_receiver_member_unknown')
                                    truth = conjunction(truth,present)
                                    continue
                                if isinstance(place,Node) and place.local_id in self.iteration_values:
                                    if any(c.kind == 'property' and c.name == 'rebound'
                                           and c.expressions[0].value.strip('"') == 'true'
                                           for c in clause.blocks[0]):
                                        # ``rebound: true;``: the binding names the element even
                                        # where a write to the loop variable precedes the
                                        # occurrence -- the walk dispatched on the element it
                                        # iterated, not on the value the variable holds there.
                                        _loop, original = self.iteration_values[place.local_id]
                                        present = original in receivers
                                    else:
                                        present = False
                                        for receiver in receivers:
                                            present = disjunction(present,iteration_value_at(place.local_id,receiver,op))
                                else:
                                    present = place.local_id in receivers if isinstance(place,Node) else Unknown('call_receiver_binding_unknown')
                                truth = conjunction(truth,present if receivers else Unknown('call_receiver_missing'))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'receiver_input':
                                # ``receiver_input: $place;`` requires the receiver *expression* of
                                # this occurrence to be that very place: the ``CALL_RECEIVER_INPUT``
                                # row a linear body publishes for the receivers it reads directly.
                                # It is stricter than ``receiver: $place;``, which accepts the
                                # receiver row alone -- ``s = Snapshot(0); return s.state; return
                                # s.get()`` still has the parameter as its receiver row, yet the
                                # receiver is the freshly built value, so only the input relation
                                # rejects it.
                                place = current.get(constraint.expressions[0].value)
                                sources = {f.object for f in rows('CALL_RECEIVER_INPUT',call.id)}
                                present = (place.local_id in sources if isinstance(place,Node)
                                           else Unknown('call_receiver_binding_unknown'))
                                truth = conjunction(truth,present if sources else False)
                                continue
                            if constraint.kind == 'property' and constraint.name == 'name':
                                # The callee spelling is part of the occurrence, so it is
                                # evidence even when no declared callable accredits the call.
                                # It is published as the entity attribute; the bound node
                                # carries it only on the paths that keep full entities.
                                # A list states the alternative primitive names the protocol
                                # is recognised under, and a regex reads a spelling the
                                # source qualified (``serde_json::to_string``) or
                                # parameterised (``Deserialize<string>``).
                                named = constraint.expressions[0]
                                role = named_role(named)
                                inventory = named.args[1] if role and named.kind == 'binary' else named
                                wanted = name_spellings(inventory) or ()
                                spelled_by = name_regex(inventory) if not wanted else None

                                def spelled(text: str) -> bool:
                                    return spelled_by.search(text) is not None if spelled_by is not None else text in wanted

                                entity = ir.entities.get(call.id) if call is not None else None
                                spelling = str(entity.attrs.get('name','')) if entity is not None else ''
                                if not spelling:
                                    spelling = next((str(f.attrs.get('name','')) for f in rows('ENTITY',call.id)
                                                     if f.attrs.get('name')),'')
                                if not spelling:
                                    spelling = str(call.name or '')
                                if role:
                                    # ``name: $action;`` exposes the spelling this call
                                    # dispatches to, so a pattern reports the action it
                                    # observed instead of enumerating every API name.
                                    # ``name: $action in [..];`` keeps the whitelist too.
                                    updated[role] = spelling
                                    if wanted or spelled_by is not None:
                                        truth = conjunction(truth,spelled(spelling))
                                    continue
                                truth = conjunction(truth,spelled(spelling))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'resolution':
                                # ``resolution: unresolved;`` asks whether the callee could be
                                # resolved: the CALL entity publishes that status.
                                wanted = constraint.expressions[0].value.strip('"')
                                if wanted == 'any':
                                    # ``resolution: any;`` states the occurrence is what the
                                    # clause is about without constraining how it resolved:
                                    # the call is still accredited as evidence, but the
                                    # constraint filters nothing.
                                    continue
                                entity = ir.entities.get(call.id)
                                status = str(entity.attrs.get('resolution','')) if entity is not None else ''
                                if not status:
                                    status = next((str(f.attrs.get('resolution','')) for f in rows('ENTITY',call.id)
                                                   if f.attrs.get('resolution')),'')
                                truth = conjunction(truth,status == wanted if status
                                                    else Unknown('call_resolution_status_missing'))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'discarded':
                                # ``discarded: true;`` states that the result of this call is
                                # not consumed: DISCARDS_RESULT(statement, call).
                                truth = conjunction(truth,any(f.object == call.id for f in rows_to('DISCARDS_RESULT',call.id)))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'returned':
                                # ``returned: true;`` states that the value this occurrence
                                # produced leaves the callable through a return statement:
                                # directly (the returned operand is the call, as
                                # RETURNS_CALL publishes it), or behind the language's
                                # runtime cast, where the returned operand is that cast.
                                statements = [operation.id for operation in ir.operations
                                              if operation.owner == owner.local_id]
                                operands = {f.object for statement in statements
                                            for f in rows('RETURN_OPERAND',statement)}
                                casts = {f.subject for f in rows_to('CAST_VALUE',call.id)}
                                # ``try_emplace(key, value).first->second`` returns a member of
                                # the object the call produced, so the walk from the call down
                                # MEMBER_OF reaches the operand. The legacy contract capped that
                                # chain at two steps, so this does too.
                                members: set[str] = set()
                                frontier = {call.id}
                                for _ in range(2):
                                    frontier = {f.subject for base in frontier
                                                for f in rows_to('MEMBER_OF',base)}
                                    members |= frontier
                                truth = conjunction(truth,
                                    call.id in operands
                                    or any(f.object == call.id for f in rows('RETURNS_CALL',owner.local_id))
                                    or any(value in operands for value in casts)
                                    or any(value in operands for value in members)
                                    # The value may also travel through a local the callable
                                    # returns (``result = f(x); return result``): the flow
                                    # analysis publishes that origin directly, which is the
                                    # relation the legacy contract named RETURN_ORIGIN.
                                    or any(f.object == call.id for statement in statements
                                           for f in rows('RETURN_ORIGIN',statement)))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'unreplaced':
                                # ``unreplaced: true;`` asks whether the place this call is
                                # dispatched on was rebound before the occurrence: the lexical
                                # prefix inventory the graph publishes as
                                # RECEIVER_UNREPLACED(call, place). A later write cannot
                                # invalidate an earlier occurrence.
                                role = next((c.expressions[0].value for c in clause.blocks[0]
                                             if c.kind == 'property' and c.name == 'receiver'),None)
                                place = current.get(role) if role else None
                                truth = conjunction(truth,
                                    any(f.object == place.local_id for f in rows('RECEIVER_UNREPLACED',call.id))
                                    if isinstance(place,Node)
                                    else Unknown('call_receiver_binding_unknown'))
                                continue
                            if constraint.kind == 'property' and constraint.name == 'receiver_version':
                                # ``receiver_version: $lifetime;`` correlates the binding a
                                # place is read through: the first occurrence that names the
                                # role binds it, every later one must read the same binding.
                                # A rebound receiver -- ``parts = other`` before the final
                                # call -- publishes a different version, so a director cannot
                                # configure one instance and finish another.
                                versions = sorted({f.object for f in rows('RECEIVER_BINDING_VERSION',call.id)})
                                if not versions:
                                    truth = conjunction(truth,Unknown('call_receiver_version_missing'))
                                else:
                                    known = current.get(constraint.expressions[0].value)
                                    if isinstance(known,Node):
                                        truth = conjunction(truth,known.local_id in versions)
                                    elif constraint.expressions[0].value in current:
                                        truth = conjunction(truth,Unknown('call_receiver_version_unknown'))
                                    else:
                                        updated[constraint.expressions[0].value] = value_node(versions[0],'VALUE')
                                continue
                            if constraint.kind == 'property' and constraint.name in OPTIONAL_ROLES:
                                truth = conjunction(truth,optional_row(constraint,call,current,
                                                                     updated,rows,value_node))
                                continue
                            if constraint.kind != 'argument':
                                continue
                            matched = False
                            parameter_positions = set()
                            if constraint.role:
                                parameter = current.get(constraint.role)
                                status = rows('BINDING_STATUS',call.id)
                                if not isinstance(parameter,Node):
                                    matched = Unknown('parameter_binding_incomplete')
                                else:
                                    for binding in rows('CALL_BINDING',call.id):
                                        if any(f.object == parameter.local_id for f in rows('BINDING_PARAMETER',binding.object)):
                                            parameter_positions.add(binding.attrs.get('position'))
                                    if not parameter_positions and not any(f.object == 'supported' for f in status):
                                        # A language without an ``explicit-arguments`` analysis
                                        # publishes no binding at all, so the pattern has to read
                                        # the parameter out of the signature: the call's resolved
                                        # or declared target *declares* that very parameter, and
                                        # the value fills its position. An explicit receiver is
                                        # declared but never passed, so the parameters after it
                                        # shift by one -- ``fn visit(&self, element)`` is called
                                        # with the element as the first argument.
                                        for target in {f.object for relation in ('TARGET','DECLARED_TARGET')
                                                       for f in rows(relation,call.id)}:
                                            declared_parameters = list(rows('HAS_PARAMETER',target))
                                            for declared in declared_parameters:
                                                if declared.object != parameter.local_id:
                                                    continue
                                                position = declared.attrs.get('position')
                                                if position is None:
                                                    continue
                                                passed = sum(1 for other in declared_parameters
                                                             if other.attrs.get('receiver')
                                                             and (other.attrs.get('position') or 0) < position)
                                                parameter_positions.add(position - passed)
                                    if not parameter_positions:
                                        matched = Unknown('parameter_binding_incomplete')
                            for argument in arguments:
                                spread = str(argument.attrs.get('kind','')).startswith('spread')
                                position = constraint.name
                                selected = (argument.attrs.get('position') in parameter_positions if constraint.role else (position == 'any' or
                                    position.startswith('"') and argument.attrs.get('name') == json.loads(position) or
                                    position.isdigit() and argument.attrs.get('kind') == 'positional' and argument.attrs.get('position') == int(position)))
                                if spread:
                                    matched = disjunction(matched,Unknown('argument_pack_unresolved'))
                                    continue
                                if not selected:
                                    continue
                                if position.isdigit() and any(str(a.attrs.get('kind','')).startswith('spread') and
                                    a.attrs.get('position',0) < argument.attrs.get('position',0) for a in arguments):
                                    matched = disjunction(matched,Unknown('argument_position_after_pack'))
                                    continue
                                derivation = next((e for e in constraint.expressions if e.kind == 'from'), None)
                                if derivation is not None:
                                    # ``argument from $input at any``: the operand is not the
                                    # place itself, it is a computation over it -- the adapter
                                    # turns its incoming parameter into the argument it delegates.
                                    origins = {f.object for f in rows('ARGUMENT_VALUE_ORIGIN', call.id)
                                               if f.attrs.get('position') == argument.attrs.get('position')}
                                    candidate = derived_from(current.get(derivation.value), origins)
                                    matched = disjunction(matched, candidate)
                                    continue
                                expected = constraint.expressions[0]
                                if expected.kind == 'call' and expected.value == 'read':
                                    expected = expected.args[0].args[0]
                                if expected.kind == 'index':
                                    # ``argument $container[$key] at any``: the operand is an
                                    # element of a bound container place. The access occurrence
                                    # carries the CONTAINER/INDEX facts; ``_`` or an unbound key
                                    # role accepts any key, because the element origin -- not the
                                    # key -- is what the pattern claims.
                                    container = current.get(expected.args[0].value)
                                    key = expected.args[1]
                                    key_node = current.get(key.value) if key.kind == 'role' else None
                                    if not isinstance(container,Node):
                                        matched = disjunction(matched,Unknown('index_container_unknown'))
                                        continue
                                    found = False
                                    for candidate in (argument.object,*(f.object for f in rows('VALUE',argument.object))):
                                        if not any(f.object == container.local_id for f in rows('CONTAINER',candidate)):
                                            continue
                                        if key.kind == 'wildcard':
                                            found = True
                                        elif isinstance(key_node,Node):
                                            found = any(f.object == key_node.local_id for f in rows('INDEX',candidate))
                                        elif key.kind == 'literal':
                                            found = any(f.attrs.get('text') == json.loads(key.value) for f in rows('INDEX',candidate))
                                        else:
                                            index = next(iter(rows('INDEX',candidate)),None)
                                            if index is None:
                                                continue
                                            updated[key.value] = value_node(index.object)
                                            found = True
                                        if found:
                                            break
                                    matched = disjunction(matched,found)
                                    continue
                                if expected.kind == 'role':
                                    binding = current.get(expected.value,Unknown('argument_binding_unknown'))
                                    if isinstance(binding,Node) and binding.local_id in self.iteration_values:
                                        candidate = iteration_value_at(binding.local_id,argument.object,op)
                                    elif isinstance(binding,Node) and binding.kind == 'VALUE':
                                        origins = [f for f in rows('ARGUMENT_VALUE_ORIGIN',call.id)
                                                   if f.attrs.get('position') == argument.attrs.get('position')]
                                        candidate = Unknown('argument_origin_missing')
                                        if origins:
                                            candidate = captured_reaches(binding.local_id, {f.object for f in origins})
                                            if candidate is True and any(f.attrs.get('modality') == 'may' for f in origins):
                                                candidate = Unknown('argument_origin_may')
                                    elif isinstance(binding,Node) and binding.kind == 'CALLABLE':
                                        from .source_callable_values import reaches
                                        candidate = (argument.object == binding.local_id
                                                     or reaches(binding.local_id,argument.object,op,operations,rows,self.check))
                                    elif isinstance(binding,Node):
                                        candidate = argument.object == binding.local_id
                                        if candidate is False and binding.kind == 'CALL':
                                            # ``argument $creation at any``: the operand is a
                                            # construction call, so an argument whose value is
                                            # that call's result carries the created value
                                            # (``Some(RealSubject { })``). The identity comes
                                            # from the published RESULT/VALUE rows, not from a
                                            # name or a position.
                                            results = {f.object for f in rows('RESULT',binding.local_id)}
                                            candidate = bool(results) and any(
                                                f.object in results for f in rows('VALUE',argument.object))
                                    elif isinstance(binding,str):
                                        candidate = Unknown('captured_value_argument_unsupported')
                                    else:
                                        candidate = Unknown('argument_binding_unknown')
                                elif expected.kind == 'wildcard':
                                    candidate = True
                                else:
                                    entity = ir.entities.get(argument.object)
                                    start = entity.attrs.get('start_byte') if entity else None
                                    end = entity.attrs.get('end_byte') if entity else None
                                    argument_operation = operation_spans.get((start,end)) if isinstance(start,int) and isinstance(end,int) else None
                                    candidate = source_matches(expected,argument_operation,current) if argument_operation else Unknown('argument_expression_missing')
                                matched = disjunction(matched,candidate)
                            truth = conjunction(truth,matched)
                        if item.kind == 'let' and truth is not False:
                            # ``let`` captures the value this call produces. Several or
                            # missing results are incomplete evidence, not a negative, and
                            # the role stays bound so later clauses can consume it.
                            produced = {f.object for f in rows('RESULT',call.id)}
                            if len(produced) == 1:
                                captured = value_node(next(iter(produced)))
                                updated[item.role] = captured
                                producers[captured.local_id] = call.id
                                if item.name:
                                    # ``let $place = call $f { ... } writes: N;`` names the
                                    # *place* the call's result was stored into, not the result
                                    # value: the enclosing declaration or assignment publishes
                                    # ``ASSIGNMENT_TARGET`` for the place it filled, and the
                                    # inventory says how many writes that place carries. This is
                                    # the call-shaped counterpart of the indexed capture, so a
                                    # pattern can index a container by a local the method derived
                                    # from a parameter -- and the place is already pinned, so the
                                    # walk stays cheap.
                                    place = None
                                    saw_place = False
                                    holder: Operation | None = op
                                    for _ in range(3):
                                        if holder is None:
                                            break
                                        for fact in rows('ASSIGNMENT_TARGET',holder.id):
                                            saw_place = True
                                            counts = rows('STORAGE_WRITE_COUNT',fact.object)
                                            if len(counts) != 1 or counts[0].object != item.name:
                                                continue
                                            statuses = rows('STORAGE_WRITE_STATUS',fact.object)
                                            if statuses and any(f.object != 'supported' for f in statuses):
                                                continue
                                            place = fact.object
                                            break
                                        if place is not None:
                                            break
                                        holder = operations.get(holder.parent) if holder.parent else None
                                    if place is None:
                                        # A place exists but its inventory disagrees with the
                                        # stated count: contradictory evidence, not a gap.
                                        truth = False if saw_place else conjunction(
                                            truth,Unknown('call_result_place_unknown'))
                                    else:
                                        kinds = [f.object for f in rows('ENTITY',place)]
                                        updated[item.role] = value_node(
                                            place,kinds[0] if len(kinds) == 1 else 'STORAGE')
                            else:
                                updated[item.role] = Unknown('call_result_incomplete')
                                truth = conjunction(truth,updated[item.role])
                elif item.kind=='break' and op.native_kind in ('break_statement','break_expression','break'):
                    loop=current.get(item.role)
                    loop_id=loop.local_id if isinstance(loop,(Node,OperationValue)) else None
                    all_operations={candidate.id:candidate for candidate in ir.operations if candidate.owner==owner.local_id}
                    ancestor=all_operations.get(op.parent or '')
                    seen=set()
                    while ancestor is not None and ancestor.id not in seen:
                        seen.add(ancestor.id)
                        if ancestor.kind in ('LOOP','SWITCH','MATCH') or ancestor.native_kind in ('switch_statement','switch_expression'):
                            break
                        ancestor=all_operations.get(ancestor.parent or '')
                    truth=(ancestor is not None and ancestor.id==loop_id and ancestor.kind=='LOOP'
                           and any(f.attrs.get('kind')=='break' for f in rows('CFG_NEXT',op.id)))
                elif item.kind == 'yield' and op.kind == 'YIELD':
                    if 'break' in op.attrs.get('tokens',()):
                        continue
                    if bool(op.attrs.get('delegated')) != ('from' in item.flags):
                        continue
                    operands=[c for c in children.get(op.id,()) if 'comment' not in c.native_kind]
                    expected=item.expressions[0]
                    if expected.kind == 'wildcard':
                        truth=True
                    elif len(operands)==1:
                        truth=source_matches(expected,operands[0],current)
                    elif not operands:
                        truth=expected.kind=='literal' and expected.value=='null'
                elif item.kind == 'return' and op.kind == 'RETURN':
                    expressions = [c for c in children.get(op.id,()) if 'comment' not in c.native_kind]
                    selected = (current.get(item.expressions[0].value)
                                if item.expressions and item.expressions[0].kind == 'role' else None)
                    derivation = (item.blocks[0][0] if item.blocks and item.blocks[0]
                                  and item.blocks[0][0].kind == 'from' else None)
                    if derivation is not None:
                        # ``return $converted from $forward;``: the method returns a value that
                        # consumes the delegated call's result, without the pattern having to
                        # name that computation.
                        origin_rows = list(rows('RETURN_ORIGIN', op.id)) or list(rows('RETURN_OPERAND', op.id))
                        candidate = derived_from(current.get(derivation.role), {f.object for f in origin_rows})
                        if candidate is False and origin_rows and all(
                                f.attrs.get('modality') == 'may' for f in origin_rows):
                            candidate = Unknown('derivation_may')
                        truth = candidate
                    elif not item.expressions:
                        truth = not expressions
                    elif item.expressions[0].kind == 'index' and len(expressions) == 1:
                        # ``return $container[$key];``: the returned value is the element
                        # this indexed read yielded. The access occurrence carries the
                        # CONTAINER/INDEX facts, exactly as it does for an indexed
                        # argument or a captured element (``let $value = $c[$k];``), so
                        # ``_`` or an unbound key role accepts any key the read uses.
                        source = item.expressions[0]
                        container_expr, key_expr = source.args
                        container = (current.get(container_expr.value)
                                     if container_expr.kind == 'role' else None)
                        key_node = (current.get(key_expr.value)
                                    if key_expr.kind == 'role' else None)
                        if not isinstance(container,Node):
                            truth = Unknown('returned_element_container_unknown')
                        else:
                            returned = [f.object for f in rows('RETURN_ORIGIN',op.id)] \
                                or [f.object for f in rows('RETURN_OPERAND',op.id)]
                            found = False
                            for candidate in returned:
                                for read in (candidate,
                                             *(f.object for f in rows('VALUE',candidate))):
                                    if not any(f.object == container.local_id
                                               for f in rows('CONTAINER',read)):
                                        continue
                                    if key_expr.kind == 'wildcard':
                                        passed = True
                                    elif isinstance(key_node,Node):
                                        passed = any(f.object == key_node.local_id
                                                     for f in rows('INDEX',read))
                                    elif key_expr.kind == 'literal':
                                        passed = any(f.attrs.get('text') == json.loads(key_expr.value)
                                                     for f in rows('INDEX',read))
                                    else:
                                        index = next(iter(rows('INDEX',read)),None)
                                        if index is None:
                                            continue
                                        updated[key_expr.value] = value_node(index.object)
                                        passed = True
                                    if passed:
                                        found = True
                                        break
                                if found:
                                    break
                            truth = found
                    elif isinstance(selected,Node) and selected.kind == 'CALLABLE':
                        # Nested function syntax owns its own operations. The
                        # return operand still identifies that function value.
                        operands = rows('RETURN_OPERAND',op.id)
                        truth = (any(f.object == selected.local_id for f in operands)
                                 if operands else Unknown('returned_callable_unknown'))
                        if truth is False:
                            for operand in operands:
                                counts = rows('STORAGE_WRITE_COUNT',operand.object)
                                statuses = rows('STORAGE_WRITE_STATUS',operand.object)
                                if len(counts) != 1 or counts[0].object != '1' or not statuses or any(f.object != 'supported' for f in statuses):
                                    continue
                                for write in operations.values():
                                    self.check()
                                    if write.parent != op.parent or write.end >= op.start:
                                        continue
                                    if (any(f.object == operand.object for f in rows('ASSIGNMENT_TARGET',write.id))
                                            and any(f.object == selected.local_id for f in rows('ASSIGNMENT_VALUE',write.id))):
                                        truth = True
                    elif len(expressions) == 1:
                        expected = item.expressions[0]
                        produced = current.get(expected.value) if expected.kind == 'role' else None
                        origin_rows = rows('RETURN_ORIGIN',op.id) if isinstance(produced,Node) and produced.kind == 'VALUE' else []
                        targets = {f.object for f in origin_rows or rows('RETURN_OPERAND',op.id)}
                        truth = (captured_reaches(produced.local_id, targets)
                                 if origin_rows and isinstance(produced,Node) else source_matches(expected,expressions[0],current,targets or None))
                        if truth is False and isinstance(produced,Node) and produced.kind in (
                                'STORAGE','PARAMETER','MEMBER','FIELD'):
                            # ``return $place`` also accepts a returned *alias* that still
                            # carries the value the place holds (``result = value; return
                            # result``): the origins the return itself yields and the
                            # origins the place was written from must agree. The body's
                            # clause order already fixes which writes precede the return.
                            yielded = {f.object for f in rows('RETURN_ORIGIN',op.id)}
                            held = {f.object for f in rows('ASSIGNED_FROM',produced.local_id)}
                            if yielded and held:
                                truth = bool(held & yielded)
                        if truth is True and any(f.attrs.get('modality') == 'may' for f in origin_rows):
                            truth = Unknown('return_origin_may')
                    copy_clause = (item.blocks[0][0] if item.blocks and item.blocks[0]
                                   and item.blocks[0][0].kind == 'copies' else None)
                    if truth is not False and copy_clause is not None:
                        # ``return $replica copies $state;``: the returned place's own
                        # field state must be a write that read the receiver's field of
                        # the same name. The flow analysis, not the query, decides which
                        # write survives aliases and branches.
                        field_role = current.get(copy_clause.role)
                        if not isinstance(field_role,Node):
                            truth = Unknown('copied_field_unbound')
                        else:
                            # The bound field role carries the member spelling, which is
                            # the name the flow analysis files the copied slot under.
                            states = [f for f in rows('RETURN_FIELD_STATE',op.id)
                                      if f.attrs.get('field') == field_role.name]
                            if not states:
                                truth = False
                            else:
                                copied = [state for state in states
                                          if any(any(f.object == field_role.local_id
                                                     for f in rows('ASSIGNMENT_VALUE',link.object))
                                                 for link in rows('FIELD_STATE_WRITE',state.object))]
                                if not copied:
                                    truth = False
                                elif all(f.attrs.get('modality') == 'may' for f in copied):
                                    truth = Unknown('copied_field_state_may')
                elif item.kind == 'assign':
                    expected_target = item.expressions[0]
                    targets = {f.object for f in rows('ASSIGNMENT_TARGET',op.id)}
                    operators = rows('OPERATOR',op.id)
                    if expected_target.kind == 'member':
                        # ``$context.state = ...`` writes a member of a retained place:
                        # the member must belong to that place and be declared by a
                        # field the pattern bound (matched by name).
                        target = member_place(expected_target,op,current,targets)
                    elif expected_target.kind == 'index':
                        # ``$registry[$key] = $value`` writes one element. The assignment
                        # targets that element's own VALUE node, which names the container
                        # it belongs to and the key the write uses.
                        container = current.get(expected_target.args[0].value)
                        key_expr = expected_target.args[1]
                        key = current.get(key_expr.value) if key_expr.kind == 'role' else None
                        target = None
                        for candidate in sorted(targets):
                            if not (isinstance(container,Node) and any(
                                    f.object == container.local_id for f in rows('CONTAINER',candidate))):
                                continue
                            if key_expr.kind == 'wildcard' or (isinstance(key,Node) and any(
                                    f.object == key.local_id for f in rows('INDEX',candidate))):
                                target = value_node(candidate,'VALUE')
                                break
                    else:
                        target = current.get(expected_target.value)
                    if (isinstance(target,Node) and target.local_id in targets
                            and (operators[0].object if operators else '=') == item.name):
                        assignment_operands = sorted(rows('OPERAND',op.id),key=lambda f:f.attrs.get('position',0))
                        rhs = ((operations.get(assignment_operands[-1].object) or unit_operation(assignment_operands[-1].object))
                               if assignment_operands else next((c for c in children.get(op.id,()) if c.role in ('right','value')),None))
                        if rhs is None:
                            # ``$place = $role;``: the frontend may publish the stored value as
                            # the assignment's ``ASSIGNMENT_VALUE`` entity instead of as an operand
                            # child, so a role bound to that very entity -- a call occurrence, a
                            # captured result -- is still the value this write stores.
                            stored = {f.object for f in rows('ASSIGNMENT_VALUE',op.id)}
                            node = current.get(item.expressions[1].value)
                            if stored and isinstance(node,Node) and node.local_id in stored:
                                truth = True
                        if rhs:
                            expected = item.expressions[1]
                            produced = current.get(expected.value) if expected.kind == 'role' else None
                            origin_rows = rows('ASSIGNMENT_ORIGIN',op.id) if isinstance(produced,Node) and produced.kind == 'VALUE' else []
                            values = {f.object for f in origin_rows or rows('ASSIGNMENT_VALUE',op.id)}
                            landing = (landed_place(producers,self.semantic,produced)
                                       if expected_target.kind == 'index' else '')
                            truth = (True if landing and landing in values
                                     else captured_reaches(produced.local_id, values)
                                     if origin_rows and isinstance(produced,Node) else source_matches(expected,rhs,updated,values or None))
                            if truth is True and any(f.attrs.get('modality') == 'may' for f in origin_rows):
                                truth = Unknown('assignment_origin_may')
                elif item.kind == 'let' and item.expressions and item.expressions[0].kind == 'index':
                    # ``let $value = $container[$key];``: the element this indexed read
                    # yielded. The access occurrence carries the CONTAINER/INDEX facts
                    # exactly as it does for an indexed argument, so ``_`` or an
                    # unbound key role accepts any key the read uses: the element
                    # origin, not the key, is what the pattern claims.
                    expected = item.expressions[0]
                    container = current.get(expected.args[0].value)
                    key = expected.args[1]
                    key_node = current.get(key.value) if key.kind == 'role' else None
                    if not isinstance(container,Node):
                        truth = Unknown('index_container_unknown')
                    else:
                        found = False
                        for row in rows('ASSIGNMENT_VALUE',op.id):
                            for candidate in (*(f.object for f in rows('VALUE',row.object)),row.object):
                                if not any(f.object == container.local_id for f in rows('CONTAINER',candidate)):
                                    continue
                                if key.kind == 'wildcard':
                                    passed = True
                                elif isinstance(key_node,Node):
                                    passed = any(f.object == key_node.local_id for f in rows('INDEX',candidate))
                                elif key.kind == 'literal':
                                    passed = any(f.attrs.get('text') == json.loads(key.value) for f in rows('INDEX',candidate))
                                else:
                                    index = next(iter(rows('INDEX',candidate)),None)
                                    if index is None:
                                        continue
                                    updated[key.value] = value_node(index.object)
                                    passed = True
                                if passed:
                                    # The read stores the element in a place. The pattern
                                    # names that place, and the write inventory says how
                                    # many writes the place carries: one unless the clause
                                    # states the count (``writes: 2``), which is what an
                                    # interning method's rewrite arm needs.
                                    for target in sorted({f.object for f in rows('ASSIGNMENT_TARGET',op.id)}):
                                        counts = rows('STORAGE_WRITE_COUNT',target)
                                        statuses = rows('STORAGE_WRITE_STATUS',target)
                                        if len(counts) != 1 or counts[0].object != (item.name or '1'):
                                            continue
                                        if statuses and any(f.object != 'supported' for f in statuses):
                                            continue
                                        kinds = [f.object for f in rows('ENTITY',target)]
                                        updated[item.role] = value_node(
                                            target,kinds[0] if len(kinds) == 1 else 'STORAGE')
                                        found = True
                                        break
                                    break
                            if found:
                                break
                        truth = found
                elif item.kind == 'selector' and op.id == group:
                    for node in local_nodes:
                        if node.kind != 'STORAGE' or item.role in current and current[item.role] != node:
                            continue
                        props = self.store.properties(node)
                        start = props.get('start_byte')
                        if props.get('declared') is not True or not isinstance(start,int) or declaration_group(start) != group:
                            continue
                        ok: QueryValue = True
                        for prop in item.blocks[0]:
                            expected = prop.expressions[0]
                            assert isinstance(expected,Expr)
                            if expected.kind == 'wildcard':
                                continue
                            if prop.name == 'type':
                                ok = conjunction(ok,matches_type(self.semantic.type_of(node),expected))
                            elif prop.name == 'type_status':
                                status = 'unknown' if is_unknown(self.semantic.type_of(node)) else 'known'
                                ok = conjunction(ok,status == (expected.value if expected.kind == 'name' else json.loads(expected.value)))
                            else:
                                ok = conjunction(ok,self.regex(node.name or '',expected) if expected.kind == 'regex' else node.name == json.loads(expected.value))
                        if ok is not False:
                            capture = {**current,item.role:node}
                            if item.alias:
                                capture[item.alias] = reference(op)
                            yield capture,is_unknown(ok),op.id
                    continue
                if truth is not False:
                    import os
                    if os.environ.get('KEN_DEBUG_INSERT') and item.kind == 'insert':
                        print('DEBUG yield insert', 'truth', truth, 'op', op.id, 'cursor', op.id)
                    if item.kind == 'let' and item.role not in updated:
                        updated[item.role] = Unknown('produced_value_unknown')
                    if item.alias:
                        if item.alias in pattern.call_aliases:
                            occurrence = calls.get((op.start,op.end))
                            updated[item.alias] = value_node(occurrence.id,'CALL') if occurrence else Unknown('call_evidence_missing')
                        else:
                            updated[item.alias] = reference(op)
                    yield updated,is_unknown(truth),op.id
        intervals: dict[tuple[str,str],tuple[set[str],bool]] = {}
        def connectors(start: str, end: str) -> tuple[set[str],bool]:
            key = (start,end)
            if key in intervals:
                return intervals[key]
            forward: set[str] = set()
            reverse: dict[str,set[str]] = {}
            todo = list(successors(start))
            connected = False
            while todo:
                self.check()
                node = todo.pop()
                if node == end:
                    connected = True
                    continue
                if node in forward:
                    continue
                forward.add(node)
                for child in successors(node):
                    reverse.setdefault(child,set()).add(node)
                    todo.append(child)
            back: set[str] = set()
            todo = [end]
            while todo:
                self.check()
                node = todo.pop()
                if node not in back:
                    back.add(node)
                    todo.extend(reverse.get(node,()))
            result = (forward & back,connected)
            intervals[key] = result
            return result
        def interval_ok(state: _State) -> QueryValue:
            if state.last is None or not state.protected and not state.forbidden_calls and not state.adjacent and not pattern.adjacent:
                return True
            if state.last == state.group:
                return (Unknown('intra_statement_effects_unresolved')
                        if state.protected or state.forbidden_calls else True)
            intermediate, connected = connectors(state.last,state.group)
            if not connected:
                return False
            if state.last in intermediate:
                return Unknown('iteration_context_unresolved')
            if (state.adjacent or pattern.adjacent) and intermediate:
                return False
            calls_known: QueryValue = True
            for role in state.forbidden_calls:
                target = state.bindings[role]
                if not isinstance(target,Node):
                    calls_known = Unknown('forbidden_call_target_unknown')
                    continue
                for group in intermediate:
                    for op in parts(group):
                        if op.kind != 'CALL':
                            continue
                        call = calls.get((op.start,op.end))
                        targets = {f.object for f in rows('TARGET',call.id)} if call else set()
                        possible = {f.object for f in rows('MAY_TARGET',call.id)} if call else set()
                        if targets == {target.local_id} and not (possible - targets):
                            return False
                        if len(targets) != 1 or possible - targets:
                            calls_known = Unknown('intermediate_call_target_incomplete')
            for role in state.protected:
                binding = state.bindings[role]
                if not isinstance(binding,Node):
                    return Unknown('protected_binding_unknown')
                for group in intermediate:
                    for op in parts(group):
                        if any(f.object == binding.local_id for f in rows('ASSIGNMENT_TARGET',op.id)):
                            return False
                        if any(f.object == binding.local_id for f in rows('ITERATION_BINDING',op.id)):
                            return False
                closure = rows('STORAGE_WRITE_STATUS',binding.local_id)
                if not closure or any(f.object != 'supported' for f in closure):
                    return Unknown('write_inventory_incomplete')
                if binding.owner != owner.local_id or binding.kind not in ('STORAGE','PARAMETER'):
                    return Unknown('nonlocal_slot_aliases_unresolved')
                if any(n.kind == 'CALLABLE' for n in local_nodes):
                    return Unknown('closure_escape_unresolved')
                if any('&' in op.attrs.get('tokens',()) or 'reference' in op.native_kind or 'ref' in op.attrs.get('tokens',()) or 'out' in op.attrs.get('tokens',()) for op in operations.values()):
                    return Unknown('slot_reference_escape_unresolved')
            return calls_known
        def completed_linear_arm(group: str, item: Clause) -> bool:
            if not linear_arm or item.kind == 'return':
                return True
            frontier = list(successors(group))
            seen = set()
            while frontier:
                self.check()
                point = frontier.pop()
                if point in seen:
                    return False
                seen.add(point)
                if any(op.kind in ('BRANCH','LOOP','TRY','SWITCH','RETURN','THROW','BREAK','CONTINUE','YIELD') for op in parts(point)):
                    return False
                frontier.extend(successors(point))
            return True

        def terminal_ok(state: _State, clause: Clause) -> QueryValue:
            restricted = {binding.local_id for role in terminal_bindings(clause)
                          if isinstance(binding := state.bindings.get(role),Node)}
            for binding in restricted:
                status = rows('STORAGE_WRITE_STATUS',binding)
                if not status or any(f.object != 'supported' for f in status):
                    return Unknown('terminal_write_inventory_unknown')
            # Sibling evaluation order is not certified. Reject a second write
            # in the anchor statement rather than silently skipping it.
            if state.last is not None:
                for op in parts(state.last,frozenset({'ASSIGN','UPDATE'})):
                    if op.id not in state.used and any(f.object in restricted for f in rows('ASSIGNMENT_TARGET',op.id)):
                        return False
            # With an initializer prefix there is no executable anchor; begin at
            # entry. Otherwise exclude the endpoint assignment's statement group.
            frontier = list(successors(state.last)) if state.last is not None else [state.group]
            seen = set()
            while frontier:
                self.check()
                point = frontier.pop()
                if point in seen:
                    continue
                seen.add(point)
                for op in parts(point,frozenset({'ASSIGN','UPDATE','BRANCH','LOOP','TRY','SWITCH'})):
                    if pattern.linear and op.kind in ('BRANCH','LOOP','TRY','SWITCH'):
                        return False
                    if any(f.object in restricted for f in rows('ASSIGNMENT_TARGET',op.id)):
                        return False
                frontier.extend(successors(point))
            return True

        pending = [_State(entries[0].object,0,bindings)]
        visited: set[object] = set()
        while pending:
            state = pending.pop()
            group,index,current,uncertain = state.group,state.index,state.bindings,state.unknown
            self.check()
            if index == len(pattern.clauses):
                yield current,uncertain
                continue
            key = (group,index,identity(tuple(sorted(current.items()))),uncertain,state.last,state.adjacent,state.used,state.protected,state.forbidden_calls,state.cursor)
            if key in visited:
                continue
            visited.add(key)
            item = pattern.clauses[index]
            if item.kind == 'where':
                condition = item.expressions[0]
                assert isinstance(condition,Expr)
                truth = self.evaluate(condition,current)
                if truth is not False:
                    pending.append(replace(state,index=index+1,unknown=uncertain or is_unknown(truth)))
                continue
            if item.kind == 'gap' and 'exit' in item.flags:
                truth = terminal_ok(state,item)
                if truth is not False:
                    yield current,uncertain or is_unknown(truth)
                continue
            if item.kind == 'gap':
                pending.append(replace(state,index=index+1,protected=protected_bindings(item),forbidden_calls=forbidden_targets(item)))
                continue
            if item.kind == 'adjacent':
                pending.append(replace(state,index=index+1,adjacent=True))
                continue
            decisions = pattern.linear and bool(parts(group,frozenset({'BRANCH','LOOP','TRY','SWITCH'})))
            if not decisions and not state.adjacent and not (pattern.adjacent and state.last is not None):
                pending.extend(replace(state,group=n,cursor=None) for n in successors(group))
            if decisions and item.kind not in ('if','iterate'):
                continue
            for matched,unknown,operation_id in match_step(item,group,current,state.cursor):
                if operation_id in state.used:
                    continue
                constraint = interval_ok(state)
                if constraint is False:
                    continue
                unknown |= is_unknown(constraint)
                if index+1 == len(pattern.clauses):
                    if completed_linear_arm(group,item):
                        yield matched,uncertain or unknown
                else:
                    used = state.used | {operation_id}
                    after = successors(group)
                    if item.kind in ('iterate','if'):
                        # The next source pattern follows the entire region,
                        # never an instruction still inside its body/arms.
                        region_op = operations[operation_id]
                        frontier,seen,exits = list(successors(operation_id)),set(),set()
                        while frontier:
                            self.check()
                            point = frontier.pop()
                            if point in seen: continue
                            seen.add(point)
                            candidate = operations.get(point)
                            if candidate is not None and region_op.start <= candidate.start and candidate.end <= region_op.end:
                                frontier.extend(successors(point))
                            else:
                                exits.add(point)
                        after = tuple(exits)
                    else:
                        pending.append(_State(group,index+1,matched,uncertain or unknown,used,group,cursor=operation_id))
                    pending.extend(_State(n,index+1,matched,uncertain or unknown,used,group) for n in after)
