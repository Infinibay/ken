"""Dart symbol + import extractor.

The Dart grammar ships inside ``tree-sitter-language-pack`` rather than a
standalone ``tree-sitter-dart`` wheel, so we pull the ``Language`` from
there. Everything downstream is the same thin shape as the other parsers.

Grammar shape worth knowing:

* Declarations and their bodies are *siblings*, not parent/child:
  ``function_signature`` is followed by a separate ``function_body``. We
  extend a declaration's line range to swallow the trailing body so the
  recorded span covers the whole function.
* Doc comments are ``documentation_comment`` sibling nodes (``///`` or
  ``/** */``), not the ``comment`` nodes the shared helpers look for, so
  Dart gets its own little doc extractor below.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule like the
# standalone ``tree_sitter_*`` modules), so it goes straight into Parser.
_PARSER = Parser(get_language("dart"))

# method_signature wraps exactly one of these inner signature nodes.
_CONSTRUCTOR_SIGS = {"constructor_signature", "factory_constructor_signature"}
_MEMBER_SIGS = {
    "function_signature",
    "getter_signature",
    "setter_signature",
    *_CONSTRUCTOR_SIGS,
}


def parse_dart_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "class_definition":
            _emit_type(child, src, "class", scope, out)
        elif kind == "mixin_declaration":
            _emit_type(child, src, "mixin", scope, out)
        elif kind == "enum_declaration":
            _emit_type(child, src, "enum", scope, out)
        elif kind == "extension_declaration":
            _emit_extension(child, src, scope, out)
        elif kind == "type_alias":
            _emit_typedef(child, src, scope, out)
        elif kind in ("function_signature", "getter_signature", "setter_signature"):
            _emit_member(child, src, kind="function", scope=scope, out=out)
        elif kind == "import_or_export":
            _emit_import(child, src, out)
        elif child.is_named:
            _walk(child, src, scope, out)


def _emit_type(node: Node, src: bytes, kind: str, scope: str, out: ParsedFile) -> None:
    name = node_text(node.child_by_field_name("name"), src) or _first_identifier(node, src)
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
            docstring=_dart_doc(node, src),
        )
    )
    body = next((c for c in node.named_children if c.type.endswith("_body")), None)
    if body is not None:
        _emit_members(body, src, qual, out)


def _emit_extension(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    """``extension StringX on String { ... }`` — the name is optional."""
    name = _first_identifier(node, src) or "<anonymous>"
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind="extension",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_dart_doc(node, src),
        )
    )
    body = next((c for c in node.named_children if c.type == "extension_body"), None)
    if body is not None:
        _emit_members(body, src, qual, out)


def _emit_typedef(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    # ``typedef IntList = List<int>;`` — the alias name is a type_identifier.
    name = next(
        (node_text(c, src) for c in node.named_children if c.type == "type_identifier"),
        None,
    )
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="typedef",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_dart_doc(node, src),
        )
    )


def _emit_members(body: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for member in body.named_children:
        if member.type == "method_signature":
            inner = member.named_children[0] if member.named_children else None
            if inner is not None and inner.type in _MEMBER_SIGS:
                _emit_member(member, src, kind=_member_kind(inner), scope=scope, out=out)
        elif member.type == "declaration":
            # Bodyless constructors land here (``A(this.x);``); fields too,
            # which we skip — only constructors are worth a symbol.
            ctor = next(
                (c for c in member.named_children if c.type in _CONSTRUCTOR_SIGS), None
            )
            if ctor is not None:
                _emit_member(member, src, kind="constructor", scope=scope, out=out)


def _emit_member(node: Node, src: bytes, kind: str, scope: str, out: ParsedFile) -> None:
    """Emit a method / getter / setter / constructor / top-level function.

    *node* is the outer node (``method_signature``/``declaration`` for class
    members, or a bare ``*_signature`` for top-level functions). The name is
    the dotted join of identifiers in the signature, e.g. ``A.named``.
    """
    sig = node
    if node.type in ("method_signature", "declaration"):
        inner = next(
            (c for c in node.named_children if c.type in _MEMBER_SIGS), None
        )
        if inner is not None:
            sig = inner
    name = _signature_name(sig, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=_decl_end_line(node),
            docstring=_dart_doc(node, src),
        )
    )


def _emit_import(node: Node, src: bytes, out: ParsedFile) -> None:
    """``import 'package:foo/bar.dart';`` / ``export '...';`` — pull the uri."""
    uri = _find_uri(node, src)
    if uri:
        out.imports.append(ParsedImport(module=uri, line=node.start_point[0] + 1))


# ---- small grammar-specific helpers ---------------------------------------


def _member_kind(inner: Node) -> str:
    if inner.type in _CONSTRUCTOR_SIGS:
        return "constructor"
    if inner.type == "getter_signature":
        return "getter"
    if inner.type == "setter_signature":
        return "setter"
    return "method"


def _signature_name(sig: Node, src: bytes) -> str | None:
    """Dotted name from a signature's direct ``identifier`` children.

    Return types (``type_identifier``/``void_type``) and parameters (nested
    under ``formal_parameter_list``) are not direct ``identifier`` children,
    so what's left is the name — ``A.named`` for a named constructor, plain
    ``hello`` for a method.
    """
    parts = [
        node_text(c, src)
        for c in sig.named_children
        if c.type == "identifier"
    ]
    parts = [p for p in parts if p]
    return ".".join(parts) if parts else None


def _first_identifier(node: Node, src: bytes) -> str | None:
    for c in node.named_children:
        if c.type == "identifier":
            return node_text(c, src)
    return None


def _decl_end_line(node: Node) -> int:
    """End line of a declaration, extended over a trailing ``function_body``
    sibling (signature and body are separate siblings in this grammar).
    """
    end = node.end_point[0]
    nxt = node.next_named_sibling
    if nxt is not None and nxt.type == "function_body":
        end = nxt.end_point[0]
    return end + 1


def _find_uri(node: Node, src: bytes) -> str | None:
    """Find the ``uri`` string anywhere under an import/export directive."""
    for c in node.named_children:
        if c.type == "uri":
            return (node_text(c, src) or "").strip("'\"")
        found = _find_uri(c, src)
        if found:
            return found
    return None


def _dart_doc(node: Node, src: bytes) -> str | None:
    """First content line of a preceding ``documentation_comment`` sibling."""
    sib = node.prev_named_sibling
    if sib is None or sib.type != "documentation_comment":
        return None
    text = node_text(sib, src) or ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("///"):
            line = line[3:].strip()
        elif line.startswith("/**"):
            line = line[3:].strip()
        else:
            line = line.lstrip("*").lstrip("/").strip()
        if line and line not in ("/**", "*/"):
            return line
    return None
