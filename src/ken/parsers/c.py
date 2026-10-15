"""C definitions and owned scopes from the existing language-pack grammar.

Coordinates always refer to the original byte source. Known Linux definition
macros keep their established logical names and use the actual compound body;
their argument syntax need not be an ordinary C parameter declaration.
"""
from __future__ import annotations

import re

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.scopes import scope_for_node
from ken.parsers.types import ParsedFile, ParsedSymbol

_PARSER = Parser(get_language('c'))
_DEFINITION_MACRO = re.compile(r'SYSCALL_DEFINE\d+|COMPAT_SYSCALL_DEFINE\d+|BPF_CALL_\d+')
_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_CONDITIONALS = frozenset(('preproc_if', 'preproc_ifdef', 'preproc_else',
                           'preproc_elif', 'preproc_elifdef'))


def parse_c_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    parsed = ParsedFile()
    _definitions(tree.root_node, source, parsed)
    return parsed


def _definitions(container: Node, source: bytes, parsed: ParsedFile,
                 owner: str | None = None) -> None:
    for node in container.named_children:
        if node.type in _CONDITIONALS:
            _definitions(node, source, parsed, owner)
            continue
        if node.type == 'function_definition':
            body = node.child_by_field_name('body')
            if body is None:
                continue
            name = (_macro_name(node, source)
                    or _function_name(node.child_by_field_name('declarator'), source))
        elif node.type == 'expression_statement':
            # Parameterized kernel macros can parse as a top-level call plus
            # a compound statement. Only the explicitly known definition
            # spellings qualify; ordinary calls and prototypes never do.
            body = node.next_named_sibling
            while body is not None and body.type == 'comment':
                body = body.next_named_sibling
            if body is None or body.type != 'compound_statement':
                continue
            name = _macro_name(node, source)
        else:
            if owner is not None:
                _definitions(node, source, parsed, owner)
            continue
        if name:
            qualname = f'{owner}.{name}' if owner else name
            symbol = ParsedSymbol('function', name, qualname,
                node.start_point[0]+1, body.end_point[0]+1)
            parsed.symbols.append(symbol)
            parsed.scopes.append(scope_for_node(source, node, symbol, body=body))
            _definitions(body, source, parsed, qualname)


def _function_name(declarator: Node | None, source: bytes) -> str | None:
    callable_declarator = False
    while declarator is not None:
        if declarator.type == 'identifier':
            return node_text(declarator, source) if callable_declarator else None
        callable_declarator |= declarator.type == 'function_declarator'
        child = declarator.child_by_field_name('declarator')
        if child is None and declarator.type == 'parenthesized_declarator':
            child = next(iter(declarator.named_children), None)
        declarator = child
    return None


def _macro_name(node: Node, source: bytes) -> str | None:
    # The grammar owns trivia, including C line-comment splices. Inspect only
    # the first three real tokens: known macro, opening paren, logical name.
    tokens: list[str] = []
    pending = [node]
    while pending and len(tokens) < 3:
        current = pending.pop()
        if current.type == 'comment':
            continue
        if current.children:
            pending.extend(reversed(current.children))
        else:
            text = node_text(current, source)
            if text is None:
                return None
            tokens.append(text)
    if (len(tokens) != 3 or not _DEFINITION_MACRO.fullmatch(tokens[0])
            or tokens[1] != '(' or not _IDENTIFIER.fullmatch(tokens[2])):
        return None
    macro, _, name = tokens
    return '__'+name if macro.startswith(('SYSCALL_DEFINE', 'COMPAT_')) else name
