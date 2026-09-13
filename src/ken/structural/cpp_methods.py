"""C++ member declarations and bounded virtual signature correspondence.

This is not overload selection or C++ type checking. Unresolved signature types
do not acquire an override merely because their source names are equal.
"""
from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any
from tree_sitter import Node

from .model import IR
from .type_refs import TypeRef, parse_type


def nested(node: Node) -> Node | None:
    child = node.child_by_field_name('declarator')
    if child is None and node.type in {'reference_declarator', 'abstract_reference_declarator', 'parenthesized_declarator'}:
        child = next((c for c in node.named_children if 'comment' not in c.type), None)
    return child


def function_parts(node: Node) -> tuple[Node, Node] | None:
    current: Node | None = node
    for _ in range(32):
        if current is None:
            return None
        if current.type == 'function_declarator':
            name = nested(current)
            while name is not None and name.type == 'parenthesized_declarator':
                name = nested(name)
            if name is not None and name.type in {'identifier', 'field_identifier', 'operator_name', 'destructor_name'}:
                return current, name
            return None  # A pointer/reference under the function layer is a callback.
        if current.type not in {'function_definition', 'pointer_declarator', 'reference_declarator'}:
            return None
        current = nested(current)
    return None


def prototype_origin(node: Node) -> Node | None:
    if node.type != 'function_declarator' or function_parts(node) is None:
        return None
    current = node
    for _ in range(32):
        parent = current.parent
        if parent is None:
            return None
        if parent.type in {'field_declaration', 'declaration'}:
            container = parent.parent
            if container is not None and container.type == 'template_declaration':
                container = container.parent
            return parent if container is not None and container.type == 'field_declaration_list' else None
        if parent.type not in {'pointer_declarator', 'reference_declarator'}:
            return None
        current = parent
    return None


def spelling(source: bytes, node: Node | None) -> str:
    return source[node.start_byte:node.end_byte].decode('utf-8', 'replace') if node is not None else ''


def abstract_type(source: bytes, origin: Node, removed: Node | None,
                  declarator: Node | None = None) -> str:
    annotation = origin.child_by_field_name('type')
    parts = [spelling(source, c) for c in origin.named_children
             if c == annotation or c.type == 'type_qualifier']
    if declarator is None:
        declarator = origin.child_by_field_name('declarator')
    if declarator is not None:
        if removed is None:
            parts.append(spelling(source, declarator))
        else:
            parts.append((source[declarator.start_byte:removed.start_byte]
                          + source[removed.end_byte:declarator.end_byte]).decode('utf-8', 'replace'))
    return ' '.join(p for p in parts if p).strip()


def parameter_info(source: bytes, node: Node) -> tuple[Node | None, str]:
    current = node.child_by_field_name('declarator')
    for _ in range(32):
        if current is None or current.type in {'identifier', 'field_identifier'}:
            break
        current = nested(current)
    name = current if current is not None and current.type in {'identifier', 'field_identifier'} else None
    return name, abstract_type(source, node, name)


def parameter_head(annotation: str) -> str | None:
    """Receiver head for simple nominal parameters, not general C++ decay/aliasing."""
    ref = parse_type(annotation, 'cpp')
    indirections = 0
    while ref.kind in {'qualified', 'pointer', 'reference', 'rvalue_reference'} and ref.arguments:
        indirections += ref.kind != 'qualified'
        ref = ref.arguments[0]
    if ref.kind == 'nominal' and indirections <= 1 and re.fullmatch(r'[A-Za-z_]\w*', ref.native):
        return ref.native
    return None


def method_info(source: bytes, node: Node, origin: Node) -> dict[str, Any]:
    parts = function_parts(node)
    if parts is None:
        return {'cpp_signature_syntax': False}
    function, name = parts
    parameters = function.child_by_field_name('parameters')
    tokens = {spelling(source, c) for c in origin.children if not c.is_named}
    qualifiers = [spelling(source, c) for c in function.named_children if c.type == 'type_qualifier']
    ref = next((spelling(source, c) for c in function.named_children if c.type == 'ref_qualifier'), '')
    specifiers = {spelling(source, c) for c in function.named_children if c.type == 'virtual_specifier'}
    # Each declarator has its own pure-specifier, even in a multi-declaration.
    root = function
    while root.parent is not None and root.parent != origin:
        root = root.parent
    tail = []
    found = False
    for child in origin.children:
        if child == root:
            found = True
            continue
        if found:
            if child.type in {',', ';'}:
                break
            if 'comment' not in child.type:
                tail.append(spelling(source, child))
    return_type = abstract_type(source, origin, function, root)
    trailing = next((c for c in function.named_children if c.type == 'trailing_return_type'), None)
    if trailing is not None:
        return_type = spelling(source, trailing).removeprefix('->').strip()
    ancestor = origin.parent
    templated = False
    while ancestor is not None:
        templated |= ancestor.type == 'template_declaration'
        ancestor = ancestor.parent
    return {
        'cpp_signature_syntax': not origin.has_error and parameters is not None
            and not templated
            and name.type != 'destructor_name',
        'declaration_only': origin.child_by_field_name('body') is None,
        'explicit_virtual': 'virtual' in tokens,
        'pure_virtual': tail == ['=', '0'],
        'override_specifier': 'override' in specifiers,
        'final_specifier': 'final' in specifiers,
        'cv_qualifiers': sorted(qualifiers), 'ref_qualifier': ref,
        'cpp_variadic': parameters is not None and any(c.type == '...' for c in parameters.children),
        'static': any(c.type == 'storage_class_specifier' and spelling(source, c) == 'static'
                      for c in origin.named_children),
        'native_return_type': return_type,
    }


def virtual_overrides(graph: IR, methods: dict[tuple[str, str], list[str]],
                      ancestors: Callable[[str], set[str]],
                      resolve: Callable[[str, str], str | None]) -> None:
    cpp_methods = {method: owner for (owner, _), items in methods.items() for method in items
                   if graph.entities[method].attrs.get('language') == 'cpp'}
    if not cpp_methods:
        return
    parameters: dict[str, list[tuple[int, str]]] = {}
    for fact in graph.facts:
        if fact.relation == 'HAS_PARAMETER' and not fact.attrs.get('receiver'):
            parameters.setdefault(fact.subject, []).append((fact.attrs['position'], fact.object))

    def key(ref: TypeRef, context: str) -> tuple | None:
        if ref.kind == 'nominal':
            resolved = resolve(ref.native, context)
            return ('nominal', resolved) if resolved else None
        if ref.kind in {'pointer', 'reference', 'rvalue_reference', 'qualified', 'array'}:
            if len(ref.arguments) != 1:
                return None
            inner = key(ref.arguments[0], context)
            return (ref.kind, tuple(sorted(ref.qualifiers)), ref.extent, inner) if inner is not None else None
        if ref.kind in {'int', 'float', 'char', 'bool', 'void'}:
            return (ref.kind, ref.native)
        return None

    signatures: dict[str, tuple] = {}
    for method in cpp_methods:
        entity = graph.entities[method]
        attrs = entity.attrs
        parts = []
        reason = ''
        if not attrs.get('cpp_signature_syntax'):
            reason = 'unsupported-declarator'
        elif attrs.get('static') or attrs.get('constructor'):
            reason = 'non-instance-method'
        else:
            for _, parameter in sorted(parameters.get(method, [])):
                ref = parse_type(graph.entities[parameter].attrs.get('native_type', ''), 'cpp')
                # Parameter adjustment and removal of top-level cv do not erase pointee cv.
                if ref.kind == 'array':
                    ref = TypeRef('pointer', ref.native, ref.arguments)
                while ref.kind == 'qualified' and ref.arguments:
                    ref = ref.arguments[0]
                item = key(ref, parameter)
                if item is None:
                    reason = 'unresolved-parameter-type'
                    break
                parts.append(item)
        if not reason:
            signatures[method] = (entity.name, tuple(parts), tuple(attrs['cv_qualifiers']),
                                  attrs['ref_qualifier'], attrs['cpp_variadic'])
        graph.add(method, 'METHOD_SIGNATURE_STATUS', 'unsupported' if reason else 'supported',
                  analysis='cpp-virtual-signatures/1', reason=reason)

    # All compatible pairs, with the actual virtual seeds propagated to descendants.
    pairs = [(impl, original) for (owner, name), impls in methods.items()
             if any(impl in signatures for impl in impls)
             for base in ancestors(owner) if base != owner
             for impl in impls for original in methods.get((base, name), [])
             if impl in signatures and original in signatures and signatures[impl] == signatures[original]]
    virtual = {method for method in signatures if graph.entities[method].attrs.get('explicit_virtual')}
    changed = True
    while changed:
        added = {impl for impl, original in pairs if original in virtual} - virtual
        changed = bool(added)
        virtual.update(added)
    for method in sorted(virtual):
        graph.add(method, 'VIRTUAL_METHOD', cpp_methods[method], basis='cpp-resolved-virtual-signature')
    for impl, original in pairs:
        if original in virtual:
            graph.add(impl, 'OVERRIDES', original, f'{graph.entities[impl].path}:{graph.entities[impl].line}',
                      basis='cpp-resolved-virtual-signature')
