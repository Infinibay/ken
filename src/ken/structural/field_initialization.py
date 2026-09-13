"""Declaration-time field values, not constructor results or heap state."""
from __future__ import annotations

from collections import defaultdict
import re
from tree_sitter import Node
from .model import Entity, IR


def text(node: Node | None) -> str:
    return (node.text or b'').decode('utf-8', 'replace') if node is not None else ''


def record_field(ir: IR, node: Node, target: str, has_initializer: bool) -> None:
    language = ir.language
    parent = node.parent
    annotation = node.child_by_field_name('type')
    if language == 'java':
        if node.type != 'variable_declarator' or parent is None or parent.type != 'field_declaration':return
        annotation = parent.child_by_field_name('type')
    elif language == 'csharp':
        if (node.type != 'variable_declarator' or parent is None or parent.type != 'variable_declaration'
                or parent.parent is None or parent.parent.type != 'field_declaration'):return
        annotation = parent.child_by_field_name('type')
    elif language in {'javascript', 'typescript'}:
        if node.type not in {'field_definition', 'public_field_definition'} or parent is None or parent.type != 'class_body':return
        name = node.child_by_field_name('property') or node.child_by_field_name('name')
        if name is None or name.type not in {'property_identifier','private_property_identifier'}:return
    elif language == 'python':
        if (node.type != 'assignment' or parent is None or parent.type != 'expression_statement'
                or parent.parent is None or parent.parent.type != 'block'
                or parent.parent.parent is None or parent.parent.parent.type != 'class_definition'):return
        left = node.child_by_field_name('left')
        if left is None or left.type != 'identifier':return
    else:return
    native_type = text(annotation).removeprefix(':').strip()
    if language == 'java':native_type += text(node.child_by_field_name('dimensions'))
    mode = 'explicit' if has_initializer else 'implicit'
    tokens = {c.type for c in node.children if not c.is_named}
    if language == 'python' and not has_initializer:mode = 'absent'
    if language == 'typescript' and tokens & {'declare','abstract'}:mode = 'absent'
    oid = f'{ir.path}::op:{node.start_byte}:{node.end_byte}:{node.type}'
    parameters: set[str] = set()
    ancestor = node.parent
    while ancestor is not None:
        for child in ancestor.named_children:
            if child.type in {'type_parameter_list','type_parameters'}:
                for parameter in child.named_children:
                    name = parameter.child_by_field_name('name')
                    parameters.add(text(name) or text(parameter))
        ancestor = ancestor.parent
    ir.add(target, 'FIELD_DECLARATION', oid, f'{ir.path}:{node.start_point.row+1}',
           initialization=mode, native_type=native_type, type_parameters=sorted(parameters),
           syntax_status='unsupported' if node.has_error else 'supported')


def field_initial_values(ir: IR, declared_types: dict[str, str]) -> None:
    declarations: dict[str, list] = defaultdict(list)
    values = {}
    for fact in ir.facts:
        if fact.relation == 'FIELD_DECLARATION':declarations[fact.subject].append(fact)
        elif fact.relation == 'ASSIGNMENT_VALUE':values[fact.subject] = fact.object
    for slot, entries in declarations.items():
        entity = ir.entities[slot]
        fact = entries[0]
        mode = fact.attrs['initialization']
        status = 'supported'
        reason = ''
        value = None
        if len(entries) != 1 or ir.diagnostics or fact.attrs['syntax_status'] != 'supported':
            status, reason = 'unsupported', 'ambiguous-or-invalid-declaration'
        elif mode == 'absent':status, reason = 'absent', 'no-runtime-initializer'
        elif mode == 'explicit':
            value = values.get(fact.object)
            if value is None:status, reason = 'unsupported', 'unmodeled-initializer'
        else:
            language = entity.attrs.get('language')
            native = fact.attrs['native_type'].strip()
            primitive = None
            literal: int | float | bool | str = 0
            if language == 'javascript':value = 'UNDEFINED'
            elif language == 'typescript':reason = 'typescript-field-emit-policy'
            elif language in {'java','csharp'}:
                # Reference-ness cannot be guessed from a container/type basename in C#.
                if language == 'java':
                    primitives = {'byte','short','int','long','float','double','boolean','char'}
                    if native and native not in primitives | {'var','void','unknown'}:value = 'NULL'
                else:
                    primitive_names = {'byte','sbyte','short','ushort','int','uint','long','ulong','nint','nuint','float','double','decimal','bool','char'}
                    target = ir.entities.get(declared_types.get(slot, ''))
                    known_reference = native.removesuffix('?') not in fact.attrs.get('type_parameters', []) and target is not None and target.attrs.get('native_kind') in {'class_declaration','interface_declaration'}
                    if (native.removesuffix('?') in {'string','object','dynamic'} or re.fullmatch(r'.+\[[,\s]*\]',native.removesuffix('?'))
                            or native.endswith('?') and native[:-1] in primitive_names or known_reference):value = 'NULL'
                if value is None:
                    if native in {'boolean','bool'}:primitive, literal = 'bool', False
                    elif native == 'char':primitive, literal = 'char', '\x00'
                    elif native in {'float','double','decimal'}:primitive, literal = 'float', 0.0
                    elif native in {'byte','sbyte','short','ushort','int','uint','long','ulong','nint','nuint'}:primitive = 'int'
                    if primitive:
                        value = slot + '/FIELD_DEFAULT'
                        ir.entities[value] = Entity(value,'VALUE','default',entity.path,entity.line,entity.end_line,
                                                   dict(language=language,type=primitive,literal_value=literal,basis='language-field-default',synthetic=True))
                    else:reason = 'unresolved-field-default'
            else:reason = 'unsupported-language'
            if value is None:status = 'unsupported'
        ir.add(slot, 'FIELD_INITIAL_STATUS', status, *fact.evidence[:1], reason=reason, initialization=mode)
        if status == 'supported' and value is not None:
            ir.add(slot, 'FIELD_INITIAL_VALUE', value, *fact.evidence[:1],
                   basis='explicit-field-initializer' if mode == 'explicit' else 'language-field-default',
                   declaration=fact.object, phase='declaration')
