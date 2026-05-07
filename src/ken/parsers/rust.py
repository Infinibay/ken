"""Rust symbol + import extractor (tree-sitter-rust)."""

from __future__ import annotations

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node, Parser

from ken.parsers._helpers import child_text, doc_from_line_comments, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_LANG = Language(tsrust.language())
_PARSER = Parser(_LANG)


def parse_rust_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope_name="", out=out)
    return out


def _walk(node: Node, src: bytes, scope_name: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_item":
            _emit_function(child, src, scope_name, out)
        elif kind == "struct_item":
            _emit_type(child, src, "struct", scope_name, out)
        elif kind == "enum_item":
            _emit_type(child, src, "enum", scope_name, out)
        elif kind == "trait_item":
            _emit_type(child, src, "trait", scope_name, out)
        elif kind == "impl_item":
            _emit_impl(child, src, out)
        elif kind == "use_declaration":
            _emit_use(child, src, out)
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
            docstring=doc_from_line_comments(node, src, prefix="///"),
        )
    )


def _emit_type(node: Node, src: bytes, kind: str, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_line_comments(node, src, prefix="///"),
        )
    )


def _emit_impl(node: Node, src: bytes, out: ParsedFile) -> None:
    """``impl Foo { fn bar() {} }`` → ``Foo.bar`` is a method.

    impl can be ``impl<T> Foo<T> for Bar<T>`` (trait impl). We use the
    *type* field as the scope ("Bar" in that case) — the trait name
    is informational and rarely what callers want to grep for.
    """
    type_node = node.child_by_field_name("type")
    scope_name = node_text(type_node, src) if type_node is not None else None
    if not scope_name:
        return
    # Strip generics: ``Foo<T>`` → ``Foo``
    bare = scope_name.split("<", 1)[0].strip()
    body = node.child_by_field_name("body")
    if body is None:
        return
    for ch in body.children:
        if ch.type == "function_item":
            _emit_function(ch, src, bare, out)


def _emit_use(node: Node, src: bytes, out: ParsedFile) -> None:
    """Pull the path out of a ``use crate::foo::bar;`` form.

    We don't try to unfold ``use foo::{a, b};`` into multiple imports —
    record the prefix once. Resolution is the future import-graph
    boost's problem.
    """
    line = node.start_point[0] + 1
    arg = node.child_by_field_name("argument")
    text = node_text(arg, src) if arg is not None else None
    if not text:
        text = node_text(node, src) or ""
        text = text.removeprefix("use").strip().rstrip(";").strip()
    if text:
        out.imports.append(ParsedImport(module=text.split("::{")[0], line=line))
