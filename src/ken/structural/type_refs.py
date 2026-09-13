"""Structured annotation types, separate from runtime nominal resolution.

Library container spellings are syntax categories, not proof of API identity.
Unknown syntax remains an opaque nominal annotation instead of losing its text.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from .model import IR


@dataclass(frozen=True)
class TypeRef:
    kind: str
    native: str
    arguments: tuple['TypeRef', ...] = ()
    bits: int | None = None
    signed: bool | None = None
    extent: str | None = None
    rank: int | None = None
    qualifiers: tuple[str, ...] = ()


def split_types(text: str, separator: str = ',') -> list[str]:
    depth = 0
    start = 0
    parts = []
    for i, char in enumerate(text):
        if char in '<[(':
            depth += 1
        elif char in '>])':
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


def parse_type(annotation: str, language: str, depth: int = 0) -> TypeRef:
    text = annotation.strip().removeprefix(':').strip()
    if not text or text == 'unknown':
        return TypeRef('unknown', text)
    if depth > 32 or len(text) > 10000:
        return TypeRef('opaque', text)

    def child(value: str) -> TypeRef:
        return parse_type(value, language, depth + 1)

    union = split_types(text, '|')
    if len(union) > 1:
        return TypeRef('union', text, tuple(child(v) for v in union))
    if text.endswith('?') and language in {'csharp', 'typescript'}:
        return TypeRef('optional', text, (child(text[:-1]),))
    if language == 'rust' and text.startswith('&'):
        inner = re.sub(r"^&\s*(?:'[a-zA-Z_]\w*\s*)?(?:mut\s+)?", '', text)
        return TypeRef('reference', text, (child(inner),))
    if language in {'cpp', 'go'} and text.startswith('*'):
        return TypeRef('pointer', text, (child(text[1:]),))
    if language == 'cpp':
        if not text.endswith('>') and re.search(r'\([^)]*[*&]', text):
            return TypeRef('opaque', text)  # Parenthesized declarator precedence is not flattened.
        qualified = re.fullmatch(r'(.+?)(?:\s+|(?<=[*&]))((?:(?:const|volatile)\s*)+)', text)
        if qualified:
            return TypeRef('qualified', text, (child(qualified[1]),), qualifiers=tuple(qualified[2].split()))
        if text.endswith('&&'):
            return TypeRef('rvalue_reference', text, (child(text[:-2]),))
    if language == 'cpp' and text.endswith(('*', '&')):
        return TypeRef('pointer' if text[-1] == '*' else 'reference', text, (child(text[:-1]),))
    if language == 'go' and text.startswith('map['):
        nesting = 1
        for i in range(4, len(text)):
            nesting += (text[i] == '[') - (text[i] == ']')
            if nesting == 0:
                return TypeRef('map', text, (child(text[4:i]), child(text[i+1:])))
    if language == 'go':
        match = re.fullmatch(r'\[([^\]]*)\](.+)', text)
        if match:
            return TypeRef('array' if match[1] else 'slice', text, (child(match[2]),), extent=match[1] or None)
    if language == 'rust' and text.startswith('[') and text.endswith(']'):
        parts = split_types(text[1:-1], ';')
        if len(parts) in {1, 2}:
            return TypeRef('array' if len(parts) == 2 else 'slice', text, (child(parts[0]),), extent=parts[1] if len(parts) == 2 else None)
    if language == 'cpp':
        qualified = re.fullmatch(r'((?:(?:const|volatile)\s+)+)(.+)', text)
        if qualified:
            return TypeRef('qualified', text, (child(qualified[2]),), qualifiers=tuple(qualified[1].split()))
    array = re.fullmatch(r'(.+)\[([,\d\s]*)\]', text)
    if array and language in {'javascript', 'typescript', 'java', 'csharp', 'cpp'}:
        if language == 'csharp':
            return TypeRef('array', text, (child(array[1]),), rank=array[2].count(',') + 1)
        return TypeRef('array', text, (child(array[1]),), extent=array[2].strip() or None)
    generic = re.fullmatch(r'([\w.:]+)\s*[<\[](.+)[>\]]', text)
    if generic:
        base = generic[1].split('::')[-1].split('.')[-1]
        names = {'list':'list','List':'list','Vec':'list','vector':'list',
                 'Array':'array','array':'array','dict':'map','Dict':'map',
                 'Map':'map','HashMap':'map','Dictionary':'map','map':'map','unordered_map':'map',
                 'set':'set','Set':'set','HashSet':'set','tuple':'tuple','Tuple':'tuple',
                 'Optional':'optional','Option':'optional','Union':'union'}
        arguments = tuple(child(v) for v in split_types(generic[2]))
        if language == 'cpp' and base == 'array' and len(arguments) == 2:
            return TypeRef('array', text, arguments[:1], extent=arguments[1].native)
        return TypeRef(names.get(base, 'generic'), text, arguments)
    if text.startswith('(') and text.endswith(')') and ',' in text:
        return TypeRef('tuple', text, tuple(child(v) for v in split_types(text[1:-1]) if v))
    if text in {'list','dict','set','tuple'} and language == 'python':
        return TypeRef({'dict':'map'}.get(text,text),text)
    if text in {'any','Any','dynamic'}:
        return TypeRef('any', text)
    if text in {'never','Never','NoReturn'}:
        return TypeRef('never', text)
    if text in {'None','NoneType','null','nil'}:
        return TypeRef('null', text)
    if text == 'void':
        return TypeRef('void', text)
    if text in {'bool','boolean','Boolean'}:
        return TypeRef('bool', text)
    if text in {'str','string','String','std::string'}:
        return TypeRef('str', text)
    if text in {'char','wchar_t','char16_t','char32_t'}:
        return TypeRef('char', text, bits=16 if text == 'char' and language in {'java','csharp'} or text == 'char16_t' else 32 if text == 'char32_t' or text == 'char' and language == 'rust' else None)
    integer = re.fullmatch(r'([iu])(8|16|32|64|128)', text)
    if integer:
        return TypeRef('int', text, bits=int(integer[2]), signed=integer[1] == 'i')
    integer = re.fullmatch(r'(u?)int(8|16|32|64)(?:_t)?', text)
    if integer:
        return TypeRef('int', text, bits=int(integer[2]), signed=not bool(integer[1]))
    if text in {'int','Int','long','short','byte','sbyte','uint','ulong','ushort','usize','isize','rune'}:
        bits = {'int':32,'uint':32,'long':64,'ulong':64,'short':16,'ushort':16,'byte':8,'sbyte':8}.get(text) if language in {'java','csharp'} else 32 if text == 'rune' else 8 if text == 'byte' and language == 'go' else None
        signed = None if language == 'python' else not (text.startswith('u') or text == 'byte' and language in {'csharp','go'})
        return TypeRef('int', text, bits=bits, signed=signed)
    if text in {'float','double','f32','f64','float32','float64'}:
        bits = 32 if text in {'f32','float32'} or text == 'float' and language in {'java','csharp'} else 64 if text in {'f64','float64'} or text == 'double' and language in {'java','csharp'} else None
        return TypeRef('float', text, bits=bits)
    if text == 'number':
        return TypeRef('number', text)
    return TypeRef('nominal' if re.fullmatch(r'[\w.:]+', text) else 'opaque', text)


def annotation_types(graph: IR) -> None:
    """Materialize parameterized syntax descriptors without changing TYPE edges."""
    existing = set()

    def materialize(ref: TypeRef, language: str) -> str:
        encoded = json.dumps([language, asdict(ref)], sort_keys=True)
        key = 'type-ref:' + hashlib.sha256(encoded.encode()).hexdigest()
        if key in existing:
            return key
        existing.add(key)
        graph.add(key, 'TYPE_KIND', ref.kind, basis='annotation-syntax')
        graph.add(key, 'TYPE_NATIVE', ref.native, basis='annotation-syntax')
        if ref.bits is not None:
            graph.add(key, 'TYPE_BITS', str(ref.bits))
        if ref.signed is not None:
            graph.add(key, 'TYPE_SIGNED', str(ref.signed).lower())
        if ref.extent is not None:
            graph.add(key, 'TYPE_EXTENT', ref.extent)
        if ref.rank is not None:
            graph.add(key, 'TYPE_RANK', str(ref.rank))
        for qualifier in ref.qualifiers:
            graph.add(key, 'TYPE_QUALIFIER', qualifier, basis='annotation-syntax')
        for position, argument in enumerate(ref.arguments):
            target = materialize(argument, language)
            graph.add(key, 'TYPE_ARGUMENT', target, position=position)
        return key

    for entity in graph.entities.values():
        literal_kind = entity.attrs.get('collection_kind') if entity.kind == 'COLLECTION' else entity.attrs.get('type') if entity.kind == 'VALUE' else None
        if literal_kind in {'int','float','str','char','bool','number','array','list','map','record'}:
            descriptor = TypeRef(literal_kind, entity.attrs.get('native_kind',''))
            graph.add(entity.id,'TYPE_REF',materialize(descriptor,entity.attrs.get('language','')),
                      f'{entity.path}:{entity.line}',basis='literal-syntax')
        for attribute, relation in [('native_type', 'TYPE_REF'), ('native_return_type', 'RETURN_TYPE_REF')]:
            annotation = entity.attrs.get(attribute)
            missing = annotation is None and ((attribute == 'native_type' and entity.kind in {'PARAMETER', 'STORAGE'})
                                              or (attribute == 'native_return_type' and entity.kind == 'CALLABLE'))
            if isinstance(annotation, str) or missing:
                language = entity.attrs.get('language', '')
                ref = parse_type(annotation or '', language)
                graph.add(entity.id, relation, materialize(ref, language),
                          f'{entity.path}:{entity.line}', basis='annotation-syntax' if annotation else 'missing-annotation')
