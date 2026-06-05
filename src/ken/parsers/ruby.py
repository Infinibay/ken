"""Ruby symbol + import extractor.

The Ruby grammar ships inside ``tree-sitter-language-pack`` (no standalone
wheel needed), so the ``Language`` comes from there — same approach as the
Dart parser. Everything downstream is the usual thin shape.

Grammar shape worth knowing:

* ``module`` / ``class`` carry a ``name`` field that is either a ``constant``
  (``class Foo``) or a ``scope_resolution`` (``class Foo::Bar``); their members
  live under a ``body`` field (``body_statement``).
* Instance methods are ``method`` nodes; ``def self.x`` / ``def Klass.x`` are
  ``singleton_method`` nodes. Both span the whole ``def ... end``.
* ``class << self`` is a ``singleton_class`` node — its methods are class
  methods, so we recurse into it without opening a new scope.
* ``require`` / ``require_relative`` / ``load`` / ``autoload`` are plain method
  ``call`` nodes; the path is a ``string`` argument we read via ``string_content``.
* Constant assignments (``GREETING = ...``, ``Foo = Struct.new(...)``) are
  ``assignment`` nodes whose ``left`` field is a ``constant``.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import doc_from_line_comments, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule), so it
# goes straight into Parser.
_PARSER = Parser(get_language("ruby"))

# Method-call names that pull another file into the load path.
_REQUIRE_CALLS = {"require", "require_relative", "load", "autoload"}


def parse_ruby_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "module":
            _emit_namespace(child, src, "module", scope, out)
        elif kind == "class":
            _emit_namespace(child, src, "class", scope, out)
        elif kind == "singleton_class":
            # ``class << self`` — its methods are class methods of the
            # enclosing scope, so recurse without opening a new namespace.
            body = child.child_by_field_name("body")
            if body is not None:
                _walk(body, src, scope, out)
        elif kind == "method":
            _emit_method(child, src, "method" if scope else "function", scope, out)
        elif kind == "singleton_method":
            _emit_method(child, src, "method", scope, out)
        elif kind == "assignment":
            _emit_constant(child, src, scope, out)
        elif kind == "call":
            _maybe_emit_require(child, src, out)
            # require lines never nest declarations, so no recursion here.
        elif kind == "body_statement":
            # Module/class bodies are wrapped; descend keeping the scope.
            _walk(child, src, scope, out)
        elif child.is_named:
            _walk(child, src, scope, out)


def _emit_namespace(
    node: Node, src: bytes, kind: str, scope: str, out: ParsedFile
) -> None:
    name = node_text(node.child_by_field_name("name"), src)
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
            docstring=doc_from_line_comments(node, src, prefix="#"),
        )
    )
    body = node.child_by_field_name("body")
    if body is not None:
        _walk(body, src, qual, out)


def _emit_method(
    node: Node, src: bytes, kind: str, scope: str, out: ParsedFile
) -> None:
    name = node_text(node.child_by_field_name("name"), src)
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
            docstring=doc_from_line_comments(node, src, prefix="#"),
        )
    )


def _emit_constant(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    """``GREETING = "hi"`` / ``Foo = Struct.new(...)`` — a constant binding.

    Only assignments whose left side is a bare ``constant`` count; ordinary
    local-variable assignments (``x = 1``) are skipped.
    """
    left = node.child_by_field_name("left")
    if left is None or left.type != "constant":
        return
    name = node_text(left, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="const",
            name=name,
            qualname=f"{scope}.{name}" if scope else name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=doc_from_line_comments(node, src, prefix="#"),
        )
    )


def _maybe_emit_require(node: Node, src: bytes, out: ParsedFile) -> None:
    """Record ``require`` / ``require_relative`` / ``load`` / ``autoload``.

    The call has no receiver and its ``method`` is an ``identifier`` such as
    ``require``. ``require_relative`` paths are resolved against the requiring
    file's directory, so we normalise them to a ``./`` form — this makes the
    indexer's relative-path resolver and external/internal classifier treat
    them as internal (consistent with ``_classify_unresolved``'s generic
    branch). ``require``/``load`` use the global load path and are left as-is
    (typically a stdlib/gem, i.e. external).
    """
    method = node.child_by_field_name("method")
    if method is None or node.child_by_field_name("receiver") is not None:
        return
    call_name = node_text(method, src)
    if call_name not in _REQUIRE_CALLS:
        return
    path = _first_string_arg(node, src)
    if not path:
        return
    if call_name == "require_relative" and not path.startswith((".", "/")):
        path = "./" + path
    out.imports.append(ParsedImport(module=path, line=node.start_point[0] + 1))


def _first_string_arg(call: Node, src: bytes) -> str | None:
    """Text of the first string literal in a call's ``argument_list``."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return None
    for arg in args.named_children:
        if arg.type == "string":
            content = next(
                (c for c in arg.named_children if c.type == "string_content"), None
            )
            text = node_text(content, src) if content is not None else None
            return text.strip() if text else None
    return None
