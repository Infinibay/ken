"""Source context within a callable, separate from exclusive canonical ownership.

This source-only experiment proves lexical containment, never call targets or
execution. Existing passages, identities and owned regions are not modified.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path

from tree_sitter import Node

from ken.parsers import detect_language
from ken.retrieval.model import EntityKey, Passage, Span
from ken.retrieval.passages import EXTRACTOR_VERSION, extract_passages
from ken.structural.frontend import FUNCTIONS, LANGUAGES, TYPES, parser_for

LEXICAL_CONTEXT_VERSION = 1
_CARRIERS = FUNCTIONS | TYPES | {
    'lexical_declaration', 'variable_declaration', 'variable_declarator',
    'assignment_expression',
}
_CALLABLE_KINDS = {'function', 'method', 'constructor'}


@dataclass(frozen=True)
class ContextPart:
    """A physical source segment retaining its existing canonical line owner."""
    owner: EntityKey | None
    span: Span
    start_byte: int
    end_byte: int
    text: str


@dataclass(frozen=True)
class SyntaxScope:
    """An AST scope and its nearest scope ancestor within this context."""
    native_kind: str
    start_byte: int
    end_byte: int
    parent_index: int | None


@dataclass(frozen=True)
class LexicalContext:
    primary: EntityKey
    source_hash: str
    generation: str
    extent: Span
    start_byte: int
    end_byte: int
    parts: tuple[ContextPart, ...]
    scopes: tuple[SyntaxScope, ...]
    relation: str = 'lexically_contains'

    @property
    def text(self) -> str:
        return ''.join(part.text for part in self.parts)


@dataclass(frozen=True)
class ContextDiagnostic:
    entity: EntityKey | None
    reason: str


@dataclass(frozen=True)
class ContextCatalog:
    contexts: dict[EntityKey, LexicalContext]
    diagnostics: tuple[ContextDiagnostic, ...]
    extractor_version: int = EXTRACTOR_VERSION
    context_version: int = LEXICAL_CONTEXT_VERSION


def _nodes(root: Node) -> list[Node]:
    result: list[Node] = []
    pending = [root]
    while pending:
        current = pending.pop()
        result.append(current)
        pending.extend(reversed(current.named_children))
    return result


def _snapshot(passages: Sequence[Passage], lines: list[bytes], path: str,
              digest: str) -> tuple[dict[int, EntityKey], dict[EntityKey, Span]]:
    ownership: dict[int, EntityKey] = {}
    extents: dict[EntityKey, Span] = {}
    for passage in passages:
        if passage.entity.path != path or passage.source_hash != digest:
            raise ValueError('canonical context path/hash differs from source')
        if passage.span.end_line > len(lines):
            raise ValueError('canonical context span leaves source')
        if passage.entity.kind != 'module':
            previous = extents.setdefault(passage.entity, passage.entity_span)
            if previous != passage.entity_span:
                raise ValueError('canonical definition extent is inconsistent')
        for line in range(passage.span.start_line, passage.span.end_line + 1):
            if not lines[line-1].strip():
                continue
            previous_owner = ownership.setdefault(line, passage.entity)
            if previous_owner != passage.entity:
                raise ValueError('canonical context ownership overlaps')
    return ownership, extents


def _scope_tree(root: Node) -> tuple[SyntaxScope, ...]:
    scopes: list[SyntaxScope] = []
    pending: list[tuple[Node, int | None]] = [(root, None)]
    while pending:
        node, ancestor = pending.pop()
        if node.type in FUNCTIONS | TYPES:
            index = len(scopes)
            scopes.append(SyntaxScope(node.type, node.start_byte, node.end_byte, ancestor))
            ancestor = index
        pending.extend((child, ancestor) for child in reversed(node.named_children))
    return tuple(scopes)


def _static_binding(node: Node | None) -> bool:
    if node is None:
        return False
    if node.type in {'identifier', 'this'}:
        return True
    if node.type == 'member_expression':
        name = node.child_by_field_name('property')
        return (name is not None and name.type in {'property_identifier', 'private_property_identifier'}
                and _static_binding(node.child_by_field_name('object')))
    return False


def _is_callable_binding(carrier: Node) -> bool:
    """Only a callable itself or its single direct binding is context source."""
    if carrier.type in FUNCTIONS:
        return True
    if carrier.type in {'lexical_declaration', 'variable_declaration'}:
        declarations = [child for child in carrier.named_children if child.type != 'comment']
        return (len(declarations) == 1 and declarations[0].type == 'variable_declarator'
                and _is_callable_binding(declarations[0]))
    if carrier.type in {'variable_declarator', 'assignment_expression'}:
        value = carrier.child_by_field_name('value') or carrier.child_by_field_name('right')
        name = carrier.child_by_field_name('name') or carrier.child_by_field_name('left')
        static = (name is not None and name.type == 'identifier'
                  if carrier.type == 'variable_declarator' else _static_binding(name))
        return static and value is not None and value.type in FUNCTIONS
    return False


def build_lexical_contexts(source: bytes, passages: Sequence[Passage], *, path: str,
                           language: str, generation: str,
                           expected_source_hash: str) -> ContextCatalog:
    """Validate one canonical snapshot, then build context for proven callables.

    The generation is a caller-supplied index/profile identity, not evidence of
    freshness by itself. Byte hash and a fresh canonical extraction are checked
    here. Missing/ambiguous AST bindings remain diagnostics; no extent envelope
    or guessed name grants access to sibling source. Blank-only lines have no
    asserted canonical owner. This builder does not select query evidence.
    """
    digest = hashlib.sha256(source).hexdigest()
    if not generation or digest != expected_source_hash:
        raise ValueError('context generation/hash is missing or stale')
    text = source.decode('utf-8')  # Refuse replacement characters that hide byte loss.
    raw_lines = source.splitlines(keepends=True)
    lines = [line.rstrip(b'\r\n') for line in raw_lines]
    if [line.decode('utf-8') for line in lines] != text.splitlines():
        raise ValueError('context requires unambiguous physical line boundaries')
    detected = detect_language(Path(path))
    if detected is None or detected[0] != language:
        raise ValueError('context language differs from canonical parser')
    parsed = detected[1](source, path)
    expected = extract_passages(source, parsed, path=path, language=language)
    ownership, extents = _snapshot(passages, lines, path, digest)
    if (ownership, extents) != _snapshot(expected, lines, path, digest):
        raise ValueError('context canonical snapshot differs from current source extraction')
    if language not in set(LANGUAGES.values()):
        return ContextCatalog({}, (ContextDiagnostic(None, 'structural_grammar_unavailable'),))
    tree = parser_for(language, path).parse(source)
    if tree.root_node.has_error:
        return ContextCatalog({}, (ContextDiagnostic(None, 'syntax_error'),))
    nodes = _nodes(tree.root_node)
    carriers: dict[Span, list[Node]] = defaultdict(list)
    for node in nodes:
        if node.type in _CARRIERS:
            carriers[Span(node.start_point[0]+1, node.end_point[0]+1)].append(node)
    counts = Counter(extents.values())
    offsets = [0]
    for line in raw_lines:
        offsets.append(offsets[-1] + len(line))
    contexts: dict[EntityKey, LexicalContext] = {}
    diagnostics: list[ContextDiagnostic] = []
    for entity, extent in extents.items():
        if entity.kind not in _CALLABLE_KINDS:
            continue
        candidates = carriers.get(extent, [])
        # One line-only canonical binding cannot disambiguate same-line scopes.
        if counts[extent] != 1 or not candidates:
            diagnostics.append(ContextDiagnostic(entity, 'ambiguous_or_partial_line_scope'))
            continue
        carrier = max(candidates, key=lambda n: n.end_byte - n.start_byte)
        scopes = _scope_tree(carrier)
        roots = [s for s in scopes if s.parent_index is None]
        first = offsets[extent.start_line-1]
        end = offsets[extent.end_line-1] + len(lines[extent.end_line-1])
        if (not _is_callable_binding(carrier) or len(roots) != 1
                or roots[0].native_kind not in FUNCTIONS
                or source[first:carrier.start_byte].strip()
                or source[carrier.end_byte:end].strip()):
            diagnostics.append(ContextDiagnostic(entity, 'ambiguous_or_partial_line_scope'))
            continue
        parts: list[ContextPart] = []
        start = extent.start_line
        while start <= extent.end_line:
            owner = ownership.get(start)
            last = start
            while last < extent.end_line and ownership.get(last+1) == owner:
                last += 1
            start_byte = offsets[start-1]
            end_byte = offsets[last] if last < extent.end_line else end
            parts.append(ContextPart(owner, Span(start, last), start_byte, end_byte,
                                     source[start_byte:end_byte].decode('utf-8')))
            start = last + 1
        contexts[entity] = LexicalContext(entity, digest, generation, extent, first,
                                         end, tuple(parts), scopes)
    return ContextCatalog(contexts, tuple(diagnostics))
