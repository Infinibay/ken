"""C# symbol + import (using-directive) extractor.

The C# grammar ships inside ``tree-sitter-language-pack`` (no standalone
wheel), so we pull the ``Language`` from there like the Dart parser does.

Grammar shape worth knowing:

* Type declarations (``class_declaration`` / ``interface_declaration`` /
  ``struct_declaration`` / ``enum_declaration`` / ``record_declaration`` /
  ``delegate_declaration``) all expose a ``name`` field and hold their
  members in a ``declaration_list`` child. Members are ``method_declaration``,
  ``constructor_declaration`` and ``property_declaration``.
* Namespaces come in two flavours: the block ``namespace_declaration`` (members
  in a ``declaration_list`` child) and the C# 10 ``file_scoped_namespace_declaration``
  whose members are *siblings* that follow it at file scope. We treat both as
  transparent scope and just recurse — qualnames stay short (``Widget.Render``),
  matching the Java parser which likewise ignores the package for qualnames.
* ``using`` directives are ``using_directive`` nodes. The imported thing is a
  *namespace* (dotted ``qualified_name``/``identifier``), optionally prefixed by
  ``global``/``static`` or aliased (``using Foo = System.Console;``).
* XML doc comments are ``///`` lines emitted as one ``comment`` node per line.
"""

from __future__ import annotations

import re

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import child_text, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule), so it goes
# straight into Parser — same pattern as the Dart parser.
_PARSER = Parser(get_language("csharp"))

# type declaration node -> ken kind
_TYPE_KINDS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "delegate_declaration": "delegate",
}

# transparent containers we recurse through without emitting a symbol
_NAMESPACES = {"namespace_declaration", "file_scoped_namespace_declaration"}


def parse_csharp_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind in _TYPE_KINDS:
            _emit_type(child, src, _TYPE_KINDS[kind], scope, out)
        elif kind == "using_directive":
            _emit_using(child, src, out)
        elif kind in _NAMESPACES:
            # Block namespaces hold members in a declaration_list child;
            # file-scoped namespaces have them as siblings. Recursing into the
            # node handles the former, and the sibling case is handled because
            # the enclosing loop keeps walking after the namespace node.
            _walk(child, src, scope, out)
        elif child.is_named:
            _walk(child, src, scope, out)


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
            docstring=_csharp_doc(node, src),
        )
    )
    # delegate/enum have no member declaration_list of methods worth surfacing.
    body = node.child_by_field_name("body")
    if body is None:
        body = next((c for c in node.named_children if c.type == "declaration_list"), None)
    if body is None:
        return
    for member in body.named_children:
        mtype = member.type
        if mtype == "method_declaration":
            _emit_member(member, src, "method", qual, out)
        elif mtype == "constructor_declaration":
            _emit_member(member, src, "constructor", qual, out)
        elif mtype == "property_declaration":
            _emit_member(member, src, "property", qual, out)
        elif mtype in _TYPE_KINDS:
            # nested types — common enough (inner classes/enums) to surface.
            _emit_type(member, src, _TYPE_KINDS[mtype], qual, out)


def _emit_member(node: Node, src: bytes, kind: str, scope: str, out: ParsedFile) -> None:
    name = child_text(node, "name", src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_csharp_doc(node, src),
        )
    )


def _emit_using(node: Node, src: bytes, out: ParsedFile) -> None:
    """``using System.Text;`` / ``using static System.Math;`` /
    ``using Foo = System.Console;`` / ``global using System.Linq;`` — record the
    imported *namespace* (the dotted path), dropping the alias and modifiers.
    """
    text = node_text(node, src) or ""
    inner = text.strip().rstrip(";").strip()
    inner = inner.removeprefix("global").strip()
    inner = inner.removeprefix("using").strip()
    inner = inner.removeprefix("static").strip()
    inner = inner.removeprefix("unsafe").strip()
    # alias form: keep the right-hand side (the real namespace/type).
    if "=" in inner:
        inner = inner.split("=", 1)[1].strip()
    if inner:
        out.imports.append(ParsedImport(module=inner, line=node.start_point[0] + 1))


def _csharp_doc(node: Node, src: bytes) -> str | None:
    """First meaningful line of a preceding ``///`` XML doc-comment block.

    Each ``///`` line is its own ``comment`` sibling. We collect the contiguous
    run above *node*, strip the ``///`` marker and XML tags, and return the first
    line that has real prose (skipping lone ``<summary>`` / ``</summary>`` tags).
    """
    sib = node.prev_named_sibling
    lines: list[str] = []
    while sib is not None and sib.type == "comment":
        text = (node_text(sib, src) or "").strip()
        if not text.startswith("///"):
            break
        lines.append(text)
        sib = sib.prev_named_sibling
    lines.reverse()
    for raw in lines:
        content = raw.lstrip("/").strip()
        content = re.sub(r"<[^>]+>", "", content).strip()  # drop XML tags
        if content:
            return content
    return None
