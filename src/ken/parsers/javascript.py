"""JavaScript symbol + import extractor (tree-sitter-javascript)."""

from __future__ import annotations

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Node, Parser

from ken.parsers._helpers import child_text, doc_from_block_comment, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_LANG = Language(tsjs.language())
_PARSER = Parser(_LANG)


def parse_js_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope_name="", out=out)
    return out


def _walk(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind in ("function_declaration", "generator_function_declaration"):
            _emit_function(child, src, scope_name, out)
        elif kind == "class_declaration":
            _emit_class(child, src, scope_name, out)
        elif kind == "import_statement":
            _emit_import(child, src, out)
        elif kind in ("lexical_declaration", "variable_declaration"):
            # `const handler = () => {...}` — surface only when the RHS
            # is a function expression (most common idiomatic export).
            _maybe_emit_arrow(child, src, scope_name, out)
        elif child.is_named:
            _walk(child, src, scope_name, out)


def _emit_function(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind="method" if scope else "function",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_block_comment(node, src),
        )
    )


def _emit_class(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind="class",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_block_comment(node, src),
        )
    )
    body = node.child_by_field_name("body")
    if body is None:
        return
    for ch in body.children:
        if ch.type == "method_definition":
            mname_node = ch.child_by_field_name("name")
            mname = node_text(mname_node, src)
            if not mname:
                continue
            out.symbols.append(
                ParsedSymbol(
                    kind="method",
                    name=mname,
                    qualname=f"{qual}.{mname}",
                    line_start=ch.start_point[0] + 1,
                    line_end=ch.end_point[0] + 1,
                    docstring=doc_from_block_comment(ch, src),
                )
            )


def _maybe_emit_arrow(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for declarator in node.children:
        if declarator.type != "variable_declarator":
            continue
        value = declarator.child_by_field_name("value")
        if value is None or value.type not in ("arrow_function", "function_expression"):
            continue
        name = child_text(declarator, "name", src)
        if not name:
            continue
        qual = f"{scope}.{name}" if scope else name
        out.symbols.append(
            ParsedSymbol(
                kind="function",
                name=name,
                qualname=qual,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                docstring=doc_from_block_comment(node, src),
            )
        )


def _emit_import(node: Node, src: bytes, out: ParsedFile) -> None:
    line = node.start_point[0] + 1
    src_node = node.child_by_field_name("source")
    text = node_text(src_node, src) if src_node is not None else None
    if text:
        out.imports.append(ParsedImport(module=text.strip("'\""), line=line))
