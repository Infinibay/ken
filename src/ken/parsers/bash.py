"""Bash / Shell symbol + import extractor.

The Bash grammar ships inside ``tree-sitter-language-pack`` (no standalone
wheel), so we pull the ``Language`` from there — same approach as the Dart
parser.

Grammar shape worth knowing:

* A function is a ``function_definition`` node whose ``name`` field is a
  ``word``. Both ``foo() { ... }`` and ``function foo { ... }`` produce the
  same node; the leading ``function`` keyword (when present) is an unnamed
  child, so the ``name`` field is the reliable place to read the name.
* Shell has no real module system — the closest thing is *sourcing* another
  script with ``source FILE`` or ``. FILE``. Those are plain ``command``
  nodes whose ``name`` field is a ``command_name`` of ``source`` / ``.`` and
  whose first ``argument`` is the path. We treat that path as an import.
* Doc comments are ``comment`` siblings starting with ``#`` — the shared
  ``doc_from_line_comments`` helper handles them with ``prefix="#"`` (the
  shebang is just another ``#`` comment, harmlessly ignored unless it sits
  directly above a function).
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import child_text, doc_from_line_comments, node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language`` (not a raw capsule), so it
# goes straight into Parser.
_PARSER = Parser(get_language("bash"))

# Builtins that pull another script into the current shell. ``.`` is the
# POSIX spelling of ``source``.
_SOURCE_BUILTINS = {"source", "."}


def parse_bash_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, scope="", out=out)
    return out


def _walk(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind == "function_definition":
            _emit_function(child, src, scope, out)
        elif kind == "command":
            _maybe_emit_source(child, src, out)
            # commands have no nested definitions to recurse into.
        elif child.is_named:
            _walk(child, src, scope, out)


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
            docstring=doc_from_line_comments(node, src, prefix="#"),
        )
    )
    # Bash functions can nest other ``function_definition`` nodes; recurse
    # into the body so they get a dotted qualname.
    body = node.child_by_field_name("body")
    if body is not None:
        _walk(body, src, qual, out)


def _maybe_emit_source(node: Node, src: bytes, out: ParsedFile) -> None:
    """Record ``source FILE`` / ``. FILE`` as an import.

    The command's ``name`` field is a ``command_name`` wrapping the builtin;
    the first ``argument`` child is the sourced path. We strip surrounding
    quotes but otherwise keep the raw string (it may contain ``$VAR`` /
    ``${VAR}`` expansions that resolution cannot follow — that's fine, it
    gets classified as an internal-gap or external by the indexer).
    """
    name_node = node.child_by_field_name("name")
    builtin = node_text(name_node, src) if name_node is not None else None
    if builtin not in _SOURCE_BUILTINS:
        return
    arg = node.child_by_field_name("argument")
    if arg is None:
        return
    text = (node_text(arg, src) or "").strip().strip("'\"")
    if text:
        out.imports.append(ParsedImport(module=text, line=node.start_point[0] + 1))
