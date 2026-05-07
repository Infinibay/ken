"""Common tree-sitter helpers shared by every parser.

Keeping them out of the language modules so each parser is a thin
file that's easy to scan when adding kinds / fixing extraction.
"""

from __future__ import annotations

from tree_sitter import Node


def node_text(node: Node | None, src: bytes) -> str | None:
    if node is None:
        return None
    try:
        return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover
        return None


def child_text(node: Node, field: str, src: bytes) -> str | None:
    """Text of the child stored under field name *field*, or None."""
    ch = node.child_by_field_name(field)
    return node_text(ch, src) if ch is not None else None


def first_line(text: str | None) -> str | None:
    """First non-empty line of a docstring/comment, trimmed."""
    if not text:
        return None
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return None


# ---- comment-based docstring extractors -----------------------------------


# Grammar-specific wrappers that sit between a declaration and its
# preceding doc comment. We treat them as transparent so e.g. an
# ``export class Foo`` finds the JSDoc that lives outside the
# ``export_statement`` node.
_TRANSPARENT_WRAPPERS = {
    "export_statement",
    "ambient_declaration",
    "decorated_definition",
}


def _start_sibling(node: Node) -> Node | None:
    """Return the previous named sibling of *node*, walking through
    transparent wrappers (export, decorator, etc.) until we either find
    a sibling or run out of acceptable parents.
    """
    cur = node
    sib = cur.prev_named_sibling
    while sib is None:
        parent = cur.parent
        if parent is None or parent.type not in _TRANSPARENT_WRAPPERS:
            return None
        cur = parent
        sib = cur.prev_named_sibling
    return sib


def doc_from_line_comments(node: Node, src: bytes, *, prefix: str) -> str | None:
    """Walk back from *node* through preceding sibling comments that start
    with *prefix* (e.g. ``///`` for Rust, ``//`` for Go) and return the
    first content line.
    """
    sib = _start_sibling(node)
    collected: list[str] = []
    while sib is not None and sib.type in ("line_comment", "comment"):
        text = node_text(sib, src) or ""
        # Tree-sitter gives us the whole `/// foo` line; strip the marker.
        stripped = text.lstrip()
        if stripped.startswith(prefix):
            content = stripped[len(prefix):].strip()
            collected.append(content)
            sib = sib.prev_named_sibling
        else:
            break
    if not collected:
        return None
    # Comments collected in reverse order; first line of doc is the
    # first non-empty after reversing.
    collected.reverse()
    for line in collected:
        if line:
            return line
    return None


def doc_from_block_comment(node: Node, src: bytes) -> str | None:
    """Return the first line of a ``/** ... */`` block comment preceding
    *node*, with the `*` margin stripped. Used for JSDoc / Javadoc.

    Different grammars name this node differently — tree-sitter-java
    uses ``block_comment``, tree-sitter-{javascript,typescript} uses
    ``comment``. We accept both.
    """
    sib = _start_sibling(node)
    while sib is not None and sib.type in ("comment", "block_comment", "line_comment"):
        text = node_text(sib, src) or ""
        if text.startswith("/**"):
            inner = text.removeprefix("/**").removesuffix("*/")
            for raw in inner.splitlines():
                s = raw.strip().lstrip("*").strip()
                if s and not s.startswith("@"):  # @param / @return etc.
                    return s
            return None
        # Some grammars emit comment chains; keep walking.
        sib = sib.prev_named_sibling
    return None


def has_field(node: Node, field: str) -> bool:
    return node.child_by_field_name(field) is not None
