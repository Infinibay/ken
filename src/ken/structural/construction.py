"""Declared construction access and counts of already resolved allocation sites.

Neither inventory proves runtime uniqueness or closes world-wide allocation flow.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from tree_sitter import Node
from .model import IR


def modifiers(node: Node) -> set[str]:
    """Read only modifier grammar tokens, never annotation arguments or comments."""
    result: set[str] = set()
    for child in node.children:
        if child.type in {'modifier', 'accessibility_modifier'}:
            result.update(c.type for c in child.children if not c.is_named)
        elif child.type == 'modifiers':
            result.update(c.type for c in child.children if not c.is_named)
        elif child.type in {'static', 'get', 'set'}:
            result.add(child.type)
    return result


def callable_access(language: str, node: Node, owner_kind: str = 'CLASS') -> dict[str, Any]:
    if language not in {'java', 'csharp', 'typescript'}:
        return {}
    tokens = modifiers(node)
    access = tokens & {'public', 'private', 'protected', 'internal'}
    allowed = ({'private', 'protected'}, {'protected', 'internal'}) if language == 'csharp' else ()
    valid = len(access) <= 1 or access in allowed
    visibility = (' '.join(sorted(access)) if access else
                  ('public' if owner_kind == 'INTERFACE' else
                   {'java': 'package', 'csharp': 'private', 'typescript': 'public'}[language]))
    name = node.child_by_field_name('name')
    constructor = (node.type == 'constructor_declaration' or
                   language == 'typescript' and node.type in {'method_definition', 'method_signature'}
                   and name is not None and name.type == 'property_identifier'
                   and name.text == b'constructor' and not tokens & {'get', 'set'})
    return dict(visibility=visibility if valid else 'unknown',
                visibility_basis='explicit-modifier' if access else 'language-default',
                visibility_status='supported' if valid and not node.has_error else 'unsupported',
                instance_constructor=constructor and 'static' not in tokens)


def constructor_inventory(ir: IR, types: dict[str, Node]) -> None:
    if ir.language not in {'java', 'csharp', 'typescript'}:
        return
    members: dict[str, set[str]] = defaultdict(set)
    for fact in ir.facts:
        if fact.relation == 'HAS_METHOD':
            members[fact.subject].add(fact.object)
    for unit, node in types.items():
        if ir.entities[unit].kind != 'CLASS':
            continue
        constructors = [ir.entities[m] for m in members[unit]
                        if ir.entities[m].attrs.get('instance_constructor')]
        supported = (node.type in {'class_declaration', 'abstract_class_declaration', 'class'}
                     and not node.has_error and not ir.diagnostics)
        if ir.language == 'csharp':
            supported = supported and 'partial' not in modifiers(node) and not any(
                c.type == 'parameter_list' for c in node.named_children)
        supported = supported and all(c.attrs.get('visibility_status') == 'supported' for c in constructors)
        private = sum(c.attrs.get('visibility') == 'private' for c in constructors)
        ir.add(unit, 'CONSTRUCTOR_INVENTORY', 'supported' if supported else 'unsupported',
               f'{ir.path}:{ir.entities[unit].line}', explicit=len(constructors), private=private,
               other=len(constructors)-private, basis='declared-instance-constructors')


def resolved_allocations(ir: IR) -> None:
    sites: dict[str, set[str]] = defaultdict(set)
    for fact in ir.facts:
        if fact.relation == 'ALLOCATES_TYPE' and fact.subject in ir.entities and ir.entities[fact.subject].kind == 'CALL':
            sites[fact.object].add(fact.subject)
    for unit, entity in ir.entities.items():
        if entity.kind == 'CLASS':
            ir.add(unit, 'RESOLVED_ALLOCATION_COUNT', str(len(sites[unit])),
                   f'{entity.path}:{entity.line}', count=len(sites[unit]), basis='explicit-resolved-sites')
