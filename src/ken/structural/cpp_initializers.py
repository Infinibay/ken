"""Explicit C++ constructor member initialization, separate from constructor calls."""
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING
from tree_sitter import Node

from .model import FactIndex, IR
from .type_refs import TypeRef, parse_type

if TYPE_CHECKING:
    from .frontend import Lowerer


def record_initializer(lowerer: Lowerer, node: Node, owner: str, cls: str) -> None:
    constructor = lowerer.ir.entities.get(owner)
    if (constructor is None or not constructor.attrs.get('constructor') or not cls
            or node.parent is None or node.parent.type != 'field_initializer_list'):
        return
    items = [c for c in node.named_children if 'comment' not in c.type]
    if len(items) != 2:
        return
    name, arguments = items
    operation = f'{lowerer.ir.path}::op:{node.start_byte}:{node.end_byte}:{node.type}'
    evidence = lowerer.evidence(node)
    lowerer.ir.add(owner, 'HAS_INITIALIZER', operation, evidence, basis='cpp-constructor-syntax')
    lowerer.ir.add(operation, 'FIELD_NAME', lowerer.text(name), evidence)
    lowerer.ir.add(operation, 'INITIALIZER_FORM', arguments.type, evidence,
                  packed=node.next_sibling is not None and node.next_sibling.type == '...')
    # mem-initializer-id lookup ignores parameters; its operands do not.
    slot = lowerer.names.get((cls, lowerer.text(name))) if name.type == 'field_identifier' else None
    if slot is not None:
        entity = lowerer.ir.entities[slot]
        if entity.kind == 'STORAGE' and not entity.attrs.get('static'):
            lowerer.ir.add(operation, 'INITIALIZES_FIELD', slot, evidence, basis='cpp-constructor-syntax')
    args = [c for c in arguments.named_children if 'comment' not in c.type]
    for position, argument in enumerate(args):
        value = lowerer.value(argument, owner, cls)
        lowerer.ir.add(operation, 'INITIALIZER_ARGUMENT', value, lowerer.evidence(argument),
                      position=position, native_kind=argument.type)


def _key(ref: TypeRef) -> tuple | None:
    if ref.kind in {'pointer', 'reference', 'rvalue_reference', 'qualified'} and len(ref.arguments) == 1:
        inner = _key(ref.arguments[0])
        return (ref.kind, tuple(sorted(ref.qualifiers)), inner) if inner is not None else None
    if ref.kind in {'int', 'float', 'char', 'bool', 'nominal', 'void'}:
        return (ref.kind, ref.native)
    return None


def _unqualified(ref: TypeRef) -> TypeRef:
    while ref.kind == 'qualified' and ref.arguments:
        ref = ref.arguments[0]
    return ref


def initializer_values(graph: IR) -> None:
    """Source-local direct values; final constructor retention is a later pass."""
    if graph.language != 'cpp':
        return
    index = FactIndex(graph)
    initializers = [f for f in index.rows('HAS_INITIALIZER') if f.attrs.get('basis') == 'cpp-constructor-syntax']
    targets = {f.subject:f.object for f in index.rows('INITIALIZES_FIELD')}
    duplicates = Counter((f.subject, targets[f.object]) for f in initializers if f.object in targets)
    parameters = {(f.subject,f.object) for f in index.rows('HAS_PARAMETER')}
    for entry in initializers:
        owner, operation = entry.subject, entry.object
        field = targets.get(operation)
        args = index.rows('INITIALIZER_ARGUMENT', operation)
        forms = index.rows('INITIALIZER_FORM', operation)
        reason = ''
        value = None
        direct = False
        if graph.diagnostics or not graph.entities[owner].attrs.get('cpp_signature_syntax'):
            reason = 'unsupported-constructor'
        elif field is None:
            reason = 'not-direct-instance-field'
        elif duplicates[(owner, field)] != 1:
            reason = 'duplicate-initializer'
        elif len(forms) != 1 or forms[0].attrs.get('packed'):
            reason = 'initializer-grammar'
        else:
            ref = _unqualified(parse_type(graph.entities[field].attrs.get('native_type',''), 'cpp'))
            scalar = ref.kind in {'int','float','char','bool'}
            if not args and (scalar or ref.kind == 'pointer'):
                value = 'NULL' if ref.kind == 'pointer' else None
            elif len(args) == 1:
                operand = args[0].object
                if ref.kind == 'pointer' and operand == 'NULL':
                    value = operand
                elif scalar and args[0].attrs.get('native_kind') in {'number_literal','char_literal','true','false'}:
                    value = operand
                elif ref.kind in {'pointer','reference','rvalue_reference','int','float','char','bool'} and (owner, operand) in parameters:
                    supplied = _unqualified(parse_type(graph.entities[operand].attrs.get('native_type',''), 'cpp'))
                    if _key(ref) is not None and _key(ref) == _key(supplied):
                        value = operand
                        direct = True
                    else:
                        reason = 'parameter-type-conversion'
                else:
                    reason = 'non-direct-value'
            else:
                reason = 'unsupported-value-initialization'
        graph.add(operation, 'CONSTRUCTOR_INITIALIZER_STATUS', 'unsupported' if reason else 'supported',
                  *entry.evidence[:1], analysis='cpp-initializers/1', reason=reason)
        if reason or field is None:
            continue
        graph.add(owner, 'WRITES', field, *entry.evidence[:1], basis='cpp-constructor-initializer')
        if value is not None:
            graph.add(operation, 'STORES_VALUE', value, *entry.evidence[:1], basis='cpp-constructor-initializer')
        if direct and value is not None:
            graph.add(operation, 'CONSTRUCTOR_INITIALIZER_INPUT', value, *entry.evidence[:1], basis='cpp-constructor-initializer')
            graph.add(field, 'ASSIGNED_FROM', value, *entry.evidence[:1], basis='cpp-constructor-initializer')
            graph.add(value, 'FLOWS_TO', field, *entry.evidence[:1], basis='cpp-constructor-initializer')
