"""Kotlin symbol + import extractor.

The Kotlin grammar ships inside ``tree-sitter-language-pack`` rather than a
standalone wheel, so we pull the ``Language`` from there (same as Dart).

Grammar shape worth knowing:

* ``class_declaration`` covers class / interface / enum / annotation / data /
  sealed — they differ only by leading keyword tokens (``interface``/``enum``)
  and ``modifiers`` children, not by node type. The name is a
  ``type_identifier`` child (there is no ``name`` field). The body is a
  ``class_body`` (or ``enum_class_body`` for enums) child.
* ``object_declaration`` and ``companion_object`` are singletons; the latter's
  name is optional (defaults to ``Companion``).
* ``function_declaration`` has no ``name`` field either — the name is the first
  ``simple_identifier`` child (a leading ``receiver_type`` for extension
  functions is a different node, so it does not interfere).
* KDoc lives in a preceding ``multiline_comment`` sibling (``/** ... */``);
  the shared block-comment helper looks for ``comment``/``block_comment`` so
  Kotlin gets its own little doc extractor below.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule like the
# standalone ``tree_sitter_*`` modules), so it goes straight into Parser.
_PARSER = Parser(get_language("kotlin"))

_BODY_TYPES = ("class_body", "enum_class_body")


def parse_kotlin_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "class_declaration":
            _emit_class(child, src, scope, out)
        elif kind == "object_declaration":
            _emit_object(child, src, scope, out, default_name=None)
        elif kind == "companion_object":
            _emit_object(child, src, scope, out, default_name="Companion")
        elif kind == "function_declaration":
            _emit_function(child, src, scope, out)
        elif kind in ("secondary_constructor", "primary_constructor"):
            _emit_constructor(child, src, scope, out)
        elif kind == "type_alias":
            _emit_typealias(child, src, scope, out)
        elif kind == "import_list":
            _emit_imports(child, src, out)
        elif child.is_named:
            _walk(child, src, scope, out)


def _emit_class(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = _type_name(node, src)
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind=_class_kind(node),
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_kdoc(node, src),
        )
    )
    body = next((c for c in node.named_children if c.type in _BODY_TYPES), None)
    if body is not None:
        _walk(body, src, qual, out)


def _emit_object(
    node: Node, src: bytes, scope: str, out: ParsedFile, default_name: str | None
) -> None:
    name = _type_name(node, src) or default_name
    if not name:
        return
    qual = f"{scope}.{name}" if scope else name
    out.symbols.append(
        ParsedSymbol(
            kind="object",
            name=name,
            qualname=qual,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_kdoc(node, src),
        )
    )
    body = next((c for c in node.named_children if c.type in _BODY_TYPES), None)
    if body is not None:
        _walk(body, src, qual, out)


def _emit_function(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = _simple_name(node, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="method" if scope else "function",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_kdoc(node, src),
        )
    )


def _emit_constructor(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    # ``constructor(...)`` only makes sense inside a type; skip the primary
    # constructor when it carries no body (it's part of the class signature).
    if not scope:
        return
    name = scope.rsplit(".", 1)[-1]
    out.symbols.append(
        ParsedSymbol(
            kind="constructor",
            name=name,
            qualname=f"{scope}.<init>",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_kdoc(node, src),
        )
    )


def _emit_typealias(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    name = _type_name(node, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="typealias",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_kdoc(node, src),
        )
    )


def _emit_imports(node: Node, src: bytes, out: ParsedFile) -> None:
    """``import com.foo.Bar`` / ``import com.foo.*`` / ``... as Baz``.

    Each ``import_header`` holds a dotted ``identifier``; a wildcard import adds
    a ``wildcard_import`` sibling and an alias adds ``import_alias``. We record
    the dotted path (without the trailing ``*``/alias) — the same shape the
    Java resolver expects.
    """
    for header in node.named_children:
        if header.type != "import_header":
            continue
        ident = next(
            (c for c in header.named_children if c.type == "identifier"), None
        )
        path = node_text(ident, src) if ident is not None else None
        if path:
            out.imports.append(
                ParsedImport(module=path, line=header.start_point[0] + 1)
            )


# ---- small grammar-specific helpers ---------------------------------------


def _class_kind(node: Node) -> str:
    """class / interface / enum from the leading keyword tokens.

    ``data``/``sealed``/``annotation`` are ``modifiers`` children, not keyword
    tokens, so they all stay ``class``; only ``interface`` and ``enum`` change
    the kind.
    """
    tokens = {c.type for c in node.children if not c.is_named}
    if "interface" in tokens:
        return "interface"
    if "enum" in tokens:
        return "enum"
    return "class"


def _type_name(node: Node, src: bytes) -> str | None:
    for c in node.named_children:
        if c.type == "type_identifier":
            return node_text(c, src)
    return None


def _simple_name(node: Node, src: bytes) -> str | None:
    for c in node.named_children:
        if c.type == "simple_identifier":
            return node_text(c, src)
    return None


def _kdoc(node: Node, src: bytes) -> str | None:
    """First content line of a preceding ``/** ... */`` ``multiline_comment``."""
    sib = node.prev_named_sibling
    if sib is None or sib.type != "multiline_comment":
        return None
    text = node_text(sib, src) or ""
    if not text.startswith("/**"):
        return None
    inner = text.removeprefix("/**").removesuffix("*/")
    for raw in inner.splitlines():
        s = raw.strip().lstrip("*").strip()
        if s and not s.startswith("@"):
            return s
    return None
