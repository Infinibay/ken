"""Go symbol + import extractor (tree-sitter-go)."""

from __future__ import annotations

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from ken.parsers._helpers import child_text, doc_from_line_comments, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_LANG = Language(tsgo.language())
_PARSER = Parser(_LANG)


def parse_go_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, out)
    return out


def _walk(node: Node, src: bytes, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_declaration":
            _emit_function(child, src, out)
        elif kind == "method_declaration":
            _emit_method(child, src, out)
        elif kind == "type_declaration":
            _emit_types(child, src, out)
        elif kind == "import_declaration":
            _emit_imports(child, src, out)
        elif child.is_named:
            _walk(child, src, out)


def _emit_function(node: Node, src: bytes, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="function",
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_line_comments(node, src, prefix="//"),
        )
    )


def _emit_method(node: Node, src: bytes, out: ParsedFile) -> None:
    """``func (s *Server) Start() error { ... }`` → method ``Server.Start``."""
    name = child_text(node, "name", src)
    if not name:
        return
    receiver_type = _receiver_type_name(node, src)
    qual = f"{receiver_type}.{name}" if receiver_type else name
    out.symbols.append(
        ParsedSymbol(
            kind="method",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_line_comments(node, src, prefix="//"),
        )
    )


def _receiver_type_name(node: Node, src: bytes) -> str | None:
    receiver = node.child_by_field_name("receiver")
    if receiver is None:
        return None
    for ch in receiver.children:
        if ch.type != "parameter_declaration":
            continue
        type_node = ch.child_by_field_name("type")
        # Could be ``type_identifier`` or ``pointer_type`` containing one.
        if type_node is None:
            continue
        if type_node.type == "type_identifier":
            return node_text(type_node, src)
        if type_node.type == "pointer_type":
            inner = node_text(type_node, src) or ""
            return inner.lstrip("*").strip() or None
    return None


def _emit_types(node: Node, src: bytes, out: ParsedFile) -> None:
    """``type Foo struct { ... }`` and ``type Bar interface { ... }``.

    A single ``type_declaration`` can contain multiple ``type_spec``s.
    """
    for spec in node.children:
        if spec.type != "type_spec":
            continue
        name = child_text(spec, "name", src)
        if not name:
            continue
        type_node = spec.child_by_field_name("type")
        if type_node is None:
            continue
        if type_node.type == "struct_type":
            kind = "struct"
        elif type_node.type == "interface_type":
            kind = "interface"
        else:
            kind = "type"
        out.symbols.append(
            ParsedSymbol(
                kind=kind,
                name=name,
                qualname=name,
                line_start=spec.start_point[0] + 1,
                line_end=spec.end_point[0] + 1,
                docstring=doc_from_line_comments(node, src, prefix="//"),
            )
        )


def _emit_imports(node: Node, src: bytes, out: ParsedFile) -> None:
    """Both single ``import "x"`` and grouped ``import ( ... )``."""
    line = node.start_point[0] + 1
    for ch in node.children:
        if ch.type == "import_spec":
            mod = _import_path(ch, src)
            if mod:
                out.imports.append(ParsedImport(module=mod, line=ch.start_point[0] + 1))
        elif ch.type == "import_spec_list":
            for spec in ch.children:
                if spec.type == "import_spec":
                    mod = _import_path(spec, src)
                    if mod:
                        out.imports.append(
                            ParsedImport(module=mod, line=spec.start_point[0] + 1)
                        )
        elif ch.type == "interpreted_string_literal":
            mod = (node_text(ch, src) or "").strip('"')
            if mod:
                out.imports.append(ParsedImport(module=mod, line=line))


def _import_path(spec: Node, src: bytes) -> str | None:
    path_node = spec.child_by_field_name("path")
    if path_node is None:
        return None
    return (node_text(path_node, src) or "").strip('"')
