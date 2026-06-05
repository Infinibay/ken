"""GraphQL SDL + executable-document symbol extractor.

The GraphQL grammar ships inside ``tree-sitter-language-pack`` rather than a
standalone wheel, so we pull the ``Language`` from there (same as Dart).

GraphQL is a schema/DSL language: the core spec has **no module/import
system**, so this parser emits no imports — ``ParsedFile.imports`` is always
empty. (Tooling like ``graphql-import`` overloads ``# import "..."`` comments,
but that is non-standard and tool-specific, so we don't chase it.) The value
is in the *symbols*: type-system definitions and their fields.

Grammar shape worth knowing:

* The grammar does **not** expose field names — ``child_by_field_name("name")``
  returns ``None`` everywhere. Names are plain ``name`` child nodes, so we hunt
  for the first direct ``name`` child instead.
* Descriptions are a leading ``description`` child wrapping a ``string_value``
  (``"..."`` or ``\"\"\"...\"\"\"``); that's GraphQL's docstring.
* Top-level definitions are wrapped: ``document`` → ``definition`` →
  ``type_system_definition`` / ``type_system_extension`` /
  ``executable_definition`` → the concrete node. We just recurse through the
  unnamed-by-purpose wrappers and dispatch on the concrete types.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedSymbol

_PARSER = Parser(get_language("graphql"))

# Concrete type-system definition node -> ken kind. The field/value members of
# these are emitted as child symbols (see _emit_members).
_TYPE_DEFS: dict[str, str] = {
    "object_type_definition": "type",
    "object_type_extension": "type",
    "interface_type_definition": "interface",
    "interface_type_extension": "interface",
    "input_object_type_definition": "input",
    "input_object_type_extension": "input",
    "enum_type_definition": "enum",
    "enum_type_extension": "enum",
    "union_type_definition": "union",
    "union_type_extension": "union",
    "scalar_type_definition": "scalar",
    "scalar_type_extension": "scalar",
    "directive_definition": "directive",
}

# Wrapper nodes we transparently descend through to reach concrete defs.
_WRAPPERS = {
    "document",
    "definition",
    "type_system_definition",
    "type_system_extension",
    "type_extension",
    "executable_definition",
}


def parse_graphql_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, out)
    return out


def _walk(node: Node, src: bytes, out: ParsedFile) -> None:
    for child in node.children:
        kind = child.type
        if kind in _TYPE_DEFS:
            _emit_type(child, src, _TYPE_DEFS[kind], out)
        elif kind == "schema_definition" or kind == "schema_extension":
            _emit_schema(child, src, out)
        elif kind == "operation_definition":
            _emit_operation(child, src, out)
        elif kind == "fragment_definition":
            _emit_fragment(child, src, out)
        elif kind in _WRAPPERS:
            _walk(child, src, out)
        elif child.is_named:
            _walk(child, src, out)


def _emit_type(node: Node, src: bytes, kind: str, out: ParsedFile) -> None:
    name = _name(node, src)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_description(node, src),
        )
    )
    _emit_members(node, src, scope=name, out=out)


def _emit_schema(node: Node, src: bytes, out: ParsedFile) -> None:
    """``schema { query: Query }`` — anonymous, so we name it ``schema``."""
    out.symbols.append(
        ParsedSymbol(
            kind="schema",
            name="schema",
            qualname="schema",
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_description(node, src),
        )
    )


def _emit_operation(node: Node, src: bytes, out: ParsedFile) -> None:
    """Executable ``query``/``mutation``/``subscription`` — kind is the op type,
    name is optional (anonymous shorthand operations have none)."""
    op = next((c for c in node.children if c.type == "operation_type"), None)
    kind = (node_text(op, src) or "operation") if op is not None else "operation"
    name = _name(node, src) or "<anonymous>"
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=None,
        )
    )


def _emit_fragment(node: Node, src: bytes, out: ParsedFile) -> None:
    """``fragment UserFields on User { ... }`` — name is under fragment_name."""
    fname = next((c for c in node.children if c.type == "fragment_name"), None)
    name = _name(fname, src) if fname is not None else None
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="fragment",
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=None,
        )
    )


def _emit_members(node: Node, src: bytes, scope: str, out: ParsedFile) -> None:
    """Emit fields / input fields / enum values as ``scope.member`` symbols."""
    for child in node.named_children:
        if child.type == "fields_definition":
            _emit_member_list(child, src, "field_definition", "field", scope, out)
        elif child.type == "input_fields_definition":
            _emit_member_list(
                child, src, "input_value_definition", "field", scope, out
            )
        elif child.type == "enum_values_definition":
            _emit_member_list(
                child, src, "enum_value_definition", "enum_value", scope, out
            )


def _emit_member_list(
    container: Node, src: bytes, node_type: str, kind: str, scope: str, out: ParsedFile
) -> None:
    for member in container.named_children:
        if member.type != node_type:
            continue
        name = _member_name(member, src)
        if not name:
            continue
        out.symbols.append(
            ParsedSymbol(
                kind=kind,
                name=name,
                qualname=f"{scope}.{name}",
                line_start=member.start_point[0] + 1,
                line_end=member.end_point[0] + 1,
                docstring=_description(member, src),
            )
        )


# ---- small grammar-specific helpers ---------------------------------------


def _name(node: Node | None, src: bytes) -> str | None:
    """First direct ``name`` child's text (the grammar has no name field)."""
    if node is None:
        return None
    for c in node.children:
        if c.type == "name":
            return node_text(c, src)
    return None


def _member_name(member: Node, src: bytes) -> str | None:
    """Field / input-value names are a direct ``name``; enum values nest it
    one level under an ``enum_value`` node."""
    direct = _name(member, src)
    if direct:
        return direct
    ev = next((c for c in member.children if c.type == "enum_value"), None)
    return _name(ev, src) if ev is not None else None


def _description(node: Node, src: bytes) -> str | None:
    """First content line of a leading ``description`` (``string_value``)."""
    desc = next((c for c in node.named_children if c.type == "description"), None)
    if desc is None:
        return None
    raw = node_text(desc, src) or ""
    raw = raw.strip()
    if raw.startswith('"""'):
        raw = raw[3:-3] if raw.endswith('"""') else raw[3:]
    elif raw.startswith('"'):
        raw = raw[1:-1] if raw.endswith('"') and len(raw) > 1 else raw[1:]
    for line in raw.splitlines():
        s = line.strip()
        if s:
            return s
    return None
