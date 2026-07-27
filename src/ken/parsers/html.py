"""HTML symbol + ``<script src>``/``<link href>`` extractor.

HTML has no functions, but a page is full of *named things somebody will search
for*, and they are not the same things a code parser looks for:

* **anchors** — any element carrying an ``id``, recorded as ``#sidebar``. An id
  is the one name in a document that is unique by contract, and it is what a
  stylesheet, a test selector and a fragment URL all point at.
* **components** — custom elements (``<my-widget>``). A hyphen in a tag name is
  the spec's own marker for "not an HTML element", so this needs no list of
  known frameworks to stay correct as they come and go.
* **named form controls** — ``<form name>``, ``<input name>`` and friends. The
  ``name`` attribute is what arrives on the server, so it is API surface.
* **title** — the document's own name, which is otherwise nowhere.

Classes are deliberately *not* symbols. A class is declared in CSS (where
``parse_css_file`` already records it as a rule) and merely used here; emitting
one symbol per use would bury every real name under thousands of duplicates.

``<script src>`` and ``<link href>`` are HTML's module mechanism and become
imports. Bare relative paths are normalised to ``./x`` for the same reason the
CSS parser does it: ken's resolver then matches them, and a missing target is
classified as an internal gap rather than an external package. Absolute and
protocol-relative URLs are left alone and fall out as external.

The grammar ships inside ``tree-sitter-language-pack`` (no standalone wheel),
same as CSS, so the ``Language`` comes from ``get_language("html")``.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

_PARSER = Parser(get_language("html"))

# Elements whose ``name`` attribute is submitted or scripted, rather than being
# an arbitrary author annotation.
_NAMED_CONTROLS = {
    "form", "input", "select", "textarea", "button", "output", "fieldset",
    "meta", "param", "map", "iframe", "object", "slot",
}


def parse_html_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, out)
    return out


def _walk(node: Node, src: bytes, out: ParsedFile) -> None:
    """Descend every named child.

    ``script_element`` and ``style_element`` are distinct node types rather
    than plain elements, so a loop that only looked at ``element`` would miss
    every script tag — which is where the imports are.
    """
    for child in node.children:
        if child.type in ("element", "script_element", "style_element"):
            _emit_element(child, src, out)
            _walk(child, src, out)
        elif child.is_named:
            _walk(child, src, out)


def _emit_element(node: Node, src: bytes, out: ParsedFile) -> None:
    start = next((c for c in node.named_children if c.type == "start_tag"), None)
    if start is None:  # a self-closing tag parses as `self_closing_tag`
        start = next(
            (c for c in node.named_children if c.type == "self_closing_tag"), None
        )
    if start is None:
        return
    tag = _tag_name(start, src)
    attrs = _attributes(start, src)
    line = node.start_point[0] + 1
    doc = _html_doc(node, src)

    if tag == "title":
        text = " ".join((_inner_text(node, src) or "").split())
        if text:
            _add(out, "title", text, line, node, doc)

    ident = attrs.get("id")
    if ident:
        _add(out, "anchor", f"#{ident}", line, node, doc)

    if tag and "-" in tag:
        _add(out, "component", tag, line, node, doc)

    name = attrs.get("name")
    if name and tag in _NAMED_CONTROLS:
        _add(out, "control", name, line, node, doc)

    if tag == "script" and attrs.get("src"):
        out.imports.append(ParsedImport(module=_normalise(attrs["src"]), line=line))
    elif tag == "link" and attrs.get("href"):
        out.imports.append(ParsedImport(module=_normalise(attrs["href"]), line=line))


def _add(out: ParsedFile, kind: str, name: str, line: int, node: Node,
         doc: str | None) -> None:
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=name,
            line_start=line,
            line_end=node.end_point[0] + 1,
            docstring=doc,
        )
    )


# ---- small grammar-specific helpers ---------------------------------------


def _tag_name(start: Node, src: bytes) -> str | None:
    node = next((c for c in start.named_children if c.type == "tag_name"), None)
    text = node_text(node, src) if node is not None else None
    return text.lower() if text else None


def _attributes(start: Node, src: bytes) -> dict[str, str]:
    """Lower-cased attribute names to their values; valueless attributes are ''."""
    out: dict[str, str] = {}
    for attr in start.named_children:
        if attr.type != "attribute":
            continue
        key_node = next(
            (c for c in attr.named_children if c.type == "attribute_name"), None
        )
        key = node_text(key_node, src) if key_node is not None else None
        if not key:
            continue
        out[key.lower()] = _attr_value(attr, src) or ""
    return out


def _attr_value(attr: Node, src: bytes) -> str | None:
    for child in attr.named_children:
        if child.type == "quoted_attribute_value":
            inner = next(
                (c for c in child.named_children if c.type == "attribute_value"), None
            )
            return node_text(inner, src) if inner is not None else ""
        if child.type == "attribute_value":  # unquoted, e.g. id=main
            return node_text(child, src)
    return None


def _inner_text(node: Node, src: bytes) -> str | None:
    parts = [
        node_text(c, src) or ""
        for c in node.named_children
        if c.type in ("text", "raw_text")
    ]
    return "".join(parts) if parts else None


def _normalise(uri: str) -> str:
    """Make a bare relative path explicitly relative (``a.js`` -> ``./a.js``)."""
    u = uri.strip()
    if (
        not u
        or u.startswith(("./", "../", "/", "~", "#", "data:", "mailto:"))
        or "://" in u
        or u.startswith("//")
    ):
        return u
    return "./" + u


def _html_doc(node: Node, src: bytes) -> str | None:
    """First content line of a preceding ``<!-- ... -->`` comment sibling."""
    sib = node.prev_named_sibling
    if sib is None or sib.type != "comment":
        return None
    text = node_text(sib, src) or ""
    inner = text.removeprefix("<!--").removesuffix("-->")
    for raw in inner.splitlines():
        line = raw.strip().strip("*").strip()
        if line:
            return line
    return None
