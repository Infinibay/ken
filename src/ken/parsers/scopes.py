"""Enrich canonical parser symbols from their existing tree, without reparsing."""
from __future__ import annotations

import re

from tree_sitter import Node

from ken.parsers.types import ParsedFile, ParsedScope, ParsedSymbol


def enrich_scopes(source: bytes, root: Node, parsed: ParsedFile) -> None:
    """Attach signatures, preceding comment blocks, and statement boundaries."""
    by_span: dict[tuple[int, int], list[Node]] = {}
    pending = [root]
    while pending:
        node = pending.pop()
        by_span.setdefault((node.start_point[0] + 1, node.end_point[0] + 1), []).append(node)
        pending.extend(node.named_children)
    for symbol in parsed.symbols:
        nodes = by_span.get((symbol.line_start, symbol.line_end), [])
        if not nodes:
            continue
        # Prefer the defining syntax over identifiers/blocks on one-line functions.
        definitions = [n for n in nodes if any(tag in n.type for tag in
                       ("declaration", "definition", "_item", "declarator"))]
        node = min(definitions or nodes, key=lambda n: n.end_byte - n.start_byte)
        parsed.scopes.append(scope_for_node(source, node, symbol))


def scope_for_node(source: bytes, node: Node, symbol: ParsedSymbol, *,
                   body: Node | None = None) -> ParsedScope:
    # A lexical declaration may carry a function inside a declarator. Its
    # language-specific binding walk already knows the exact callable body.
    if body is None:
        body = node.child_by_field_name("body")
    value = node.child_by_field_name("value") or node.child_by_field_name("right")
    if body is None and value is not None:
        body = value.child_by_field_name("body")
    signature = source[node.start_byte:body.start_byte if body else node.end_byte].decode(
        "utf-8", errors="replace").rstrip()
    annotations = annotations_for_node(source, node)
    prefix = [a for a in annotations if a not in signature]
    if prefix:
        signature = "\n".join((*prefix, signature))
    comment_owner = node
    while (comment_owner.parent is not None
           and comment_owner.parent.type in ("export_statement", "lexical_declaration",
                                              "variable_declaration", "expression_statement")):
        comment_owner = comment_owner.parent
    comments: list[str] = []
    previous = comment_owner.prev_named_sibling
    while previous is not None:
        if "comment" in previous.type:
            if any(c.type == 'inner_doc_comment_marker' for c in previous.named_children):
                break  # Rust inner docs describe the enclosing module/type.
            prior = previous.prev_named_sibling
            if (prior is not None and 'comment' not in prior.type
                    and prior.type != 'attribute_item'
                    and not any(c.type == 'outer_doc_comment_marker' for c in previous.named_children)
                    and prior.end_point[0] == previous.start_point[0]):
                break  # A trailing comment describes the preceding item.
            comments.append(source[previous.start_byte:previous.end_byte].decode(
                "utf-8", errors="replace").rstrip("\r\n"))
        elif previous.type != "attribute_item":
            break
        # Rust attributes annotate this declaration and may be interleaved
        # with its doc comments. Attribute values are not comment text.
        previous = previous.prev_named_sibling
    documentation = symbol.docstring
    if comments:
        text = "\n".join(reversed(comments))
        text = re.sub(r"/\*+|\*/", "", text)
        text = "\n".join(re.sub(r"^\s*(?:///|//|\*)\s?", "", line) for line in text.splitlines()).strip()
        documentation = text or documentation
    owner = symbol.qualname.rsplit(".", 1)[0] if "." in symbol.qualname else None
    scope = ParsedScope(symbol, signature, documentation, owner,
        [(n.start_point[0] + 1, n.end_point[0] + 1) for n in body.named_children] if body else [])
    executable = next((n for n in body.named_children if "comment" not in n.type), None) if body else None
    scope.implementation_start_line = executable.start_point[0] + 1 if executable else symbol.line_start
    scope.annotations = annotations
    return scope


def annotations_for_node(source: bytes, node: Node) -> tuple[str, ...]:
    """Read attributes from the declaration and its enclosing compilation scope."""
    annotations = []
    current: Node | None = node
    while current is not None:
        previous = current.prev_named_sibling
        while previous is not None:
            if previous.type in ("attribute_item", "decorator", "annotation"):
                annotations.append(source[previous.start_byte:previous.end_byte].decode("utf-8"))
            elif "comment" not in previous.type:
                break
            previous = previous.prev_named_sibling
        current = current.parent
    return tuple(dict.fromkeys(reversed(annotations)))
