"""Lexical callable bindings in JavaScript and TypeScript, including assignments."""
from __future__ import annotations

from tree_sitter import Node

from ken.parsers.scopes import enrich_scopes, scope_for_node
from ken.parsers.types import ParsedFile, ParsedSymbol

_FUNCTIONS = {"arrow_function", "function_expression", "generator_function"}


def _text(node: Node | None, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8") if node is not None else ""


def _static_target(node: Node | None, source: bytes) -> str | None:
    if node is None:
        return None
    if node.type in ("identifier", "property_identifier", "private_property_identifier", "this"):
        return _text(node, source)
    if node.type == "member_expression":
        receiver = _static_target(node.child_by_field_name("object"), source)
        name = _static_target(node.child_by_field_name("property"), source)
        return receiver + "." + name if receiver and name else None
    # A computed runtime key does not establish a stable declaration name.
    return None


def enrich_ecmascript_scopes(source: bytes, root: Node, parsed: ParsedFile) -> None:
    enrich_scopes(source, root, parsed)
    existing = {(s.name, s.line_start, s.line_end): s for s in parsed.symbols}
    scopes = {id(s.symbol): s for s in parsed.scopes}

    def walk(node: Node, owner: str = "", parent_kind: str | None = None) -> None:
        carrier, body, name, kind = node, None, None, None
        if node.type in ("function_declaration", "generator_function_declaration", "class_declaration", "method_definition"):
            name = _text(node.child_by_field_name("name"), source)
            kind = ("class" if node.type == "class_declaration" else
                    "method" if node.type == "method_definition" or parent_kind == "class" else "function")
            body = node.child_by_field_name("body")
        elif node.type in ("variable_declarator", "assignment_expression"):
            value = node.child_by_field_name("value") or node.child_by_field_name("right")
            if value is not None and value.type in _FUNCTIONS:
                name = _static_target(node.child_by_field_name("name") or node.child_by_field_name("left"), source)
                kind, body = "function", value.child_by_field_name("body")
                if name is not None and node.type == "variable_declarator" and node.parent is not None:
                    old = existing.get((name, node.parent.start_point[0] + 1, node.parent.end_point[0] + 1))
                    if old is not None:
                        carrier = node.parent
        if name and kind:
            qualname = owner + "." + name if owner else name
            symbol = existing.get((name.rsplit(".", 1)[-1], carrier.start_point[0] + 1, carrier.end_point[0] + 1))
            if symbol is None:
                symbol = ParsedSymbol(kind, name.rsplit(".", 1)[-1], qualname,
                                      carrier.start_point[0] + 1, carrier.end_point[0] + 1)
            else:
                symbol.qualname = qualname
                symbol.kind = kind
            scopes[id(symbol)] = scope_for_node(source, carrier, symbol, body=body)
            if body is not None:
                for child in body.named_children:
                    walk(child, qualname, kind)
            return
        for child in node.named_children:
            walk(child, owner, parent_kind)

    walk(root)
    parsed.scopes = sorted(scopes.values(), key=lambda s: (s.symbol.line_start, -s.symbol.line_end, s.symbol.qualname))
