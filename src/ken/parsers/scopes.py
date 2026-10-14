"""Enrich canonical parser symbols from their existing tree, without reparsing."""
from __future__ import annotations

import re

from tree_sitter import Node

from ken.parsers.types import ParsedFile, ParsedScope


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
        body = node.child_by_field_name("body")
        value = node.child_by_field_name("value")
        if body is None and value is not None:
            body = value.child_by_field_name("body")
        signature = source[node.start_byte:body.start_byte if body else node.end_byte].decode(
            "utf-8", errors="replace").rstrip()
        comment_owner = node
        while (comment_owner.parent is not None
               and comment_owner.parent.type in ("export_statement", "lexical_declaration",
                                                  "variable_declaration")):
            comment_owner = comment_owner.parent
        comments: list[str] = []
        previous = comment_owner.prev_named_sibling
        while previous is not None and "comment" in previous.type:
            comments.append(source[previous.start_byte:previous.end_byte].decode(
                "utf-8", errors="replace"))
            previous = previous.prev_named_sibling
        documentation = symbol.docstring
        if comments:
            text = "\n".join(reversed(comments))
            text = re.sub(r"/\*+|\*/", "", text)
            text = "\n".join(re.sub(r"^\s*(?:///|//|\*)\s?", "", line)
                             for line in text.splitlines()).strip()
            documentation = text or documentation
        owner = symbol.qualname.rsplit(".", 1)[0] if "." in symbol.qualname else None
        parsed.scopes.append(ParsedScope(
            symbol, signature, documentation, owner,
            [(n.start_point[0] + 1, n.end_point[0] + 1) for n in body.named_children]
            if body else [],
        ))
