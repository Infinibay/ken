"""CSS symbol + @import extractor.

CSS has no functions/classes, but it does have grep-worthy *named things*:

* **rule sets** — a selector list (``.btn, .btn-primary``) over a block. We
  record one symbol per rule, named by its (whitespace-collapsed) selector
  text, so a search for ``.btn`` / ``btn`` lands on the rule.
* **@keyframes** — animation names (``keyframes_name``).
* **custom properties** — CSS variables (``--main-color``) declared in any
  block (commonly ``:root``); these are real reusable design tokens.

The grammar ships inside ``tree-sitter-language-pack`` (no standalone wheel),
same as Dart, so the ``Language`` comes from ``get_language("css")``.

``@import`` is CSS's only module mechanism. The imported path is resolved
relative to the importing stylesheet, so we normalise a bare ``theme.css``
to ``./theme.css``: that makes ken's generic relative-path resolver match it
and ken's unresolved-classifier treat a missing target as an internal gap
rather than an external package. Absolute URLs (``http(s)://``, ``//host``)
and ``~package`` specifiers are left untouched and fall out as external.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedImport, ParsedSymbol

# language-pack hands back a ready ``Language``, straight into Parser.
_PARSER = Parser(get_language("css"))


def parse_css_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    _walk(tree.root_node, source, out)
    return out


def _walk(node: Node, src: bytes, out: ParsedFile) -> None:
    """Descend the tree, emitting symbols/imports for the nodes we care about.

    We recurse into every named child so rule sets nested inside ``@media`` /
    ``@supports`` blocks are picked up, and custom-property declarations are
    found wherever they live.
    """
    for child in node.children:
        kind = child.type
        if kind == "import_statement":
            _emit_import(child, src, out)
        elif kind == "rule_set":
            _emit_rule(child, src, out)
            _walk(child, src, out)  # nested rules / variables inside the block
        elif kind == "keyframes_statement":
            _emit_keyframes(child, src, out)
        elif kind == "declaration":
            _emit_variable(child, src, out)
        elif child.is_named:
            _walk(child, src, out)


def _emit_rule(node: Node, src: bytes, out: ParsedFile) -> None:
    sel = next((c for c in node.named_children if c.type == "selectors"), None)
    name = _collapse(node_text(sel, src)) if sel is not None else None
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="rule",
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_css_doc(node, src),
        )
    )


def _emit_keyframes(node: Node, src: bytes, out: ParsedFile) -> None:
    name_node = next(
        (c for c in node.named_children if c.type == "keyframes_name"), None
    )
    name = node_text(name_node, src) if name_node is not None else None
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind="keyframes",
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=_css_doc(node, src),
        )
    )


def _emit_variable(node: Node, src: bytes, out: ParsedFile) -> None:
    """A ``declaration`` whose property is a custom property (``--foo``)."""
    prop = next(
        (c for c in node.named_children if c.type == "property_name"), None
    )
    name = node_text(prop, src) if prop is not None else None
    if not name or not name.startswith("--"):
        return
    out.symbols.append(
        ParsedSymbol(
            kind="variable",
            name=name,
            qualname=name,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=None,
        )
    )


def _emit_import(node: Node, src: bytes, out: ParsedFile) -> None:
    """``@import "a.css";`` / ``@import url("a.css");`` — pull the path."""
    uri = _import_uri(node, src)
    if uri:
        out.imports.append(
            ParsedImport(module=_normalise(uri), line=node.start_point[0] + 1)
        )


# ---- small grammar-specific helpers ---------------------------------------


def _import_uri(node: Node, src: bytes) -> str | None:
    """The first stylesheet path under an ``@import`` directive.

    The path is either a ``string_value`` directly, or the argument of a
    ``url(...)`` ``call_expression`` (a ``string_value`` or bare ``plain_value``).
    """
    for c in node.named_children:
        if c.type == "string_value":
            return (node_text(c, src) or "").strip("'\"")
        if c.type == "call_expression":
            args = next(
                (a for a in c.named_children if a.type == "arguments"), None
            )
            if args is None:
                continue
            for a in args.named_children:
                if a.type in ("string_value", "plain_value"):
                    return (node_text(a, src) or "").strip("'\"")
    return None


def _normalise(uri: str) -> str:
    """Make a bare relative path explicitly relative (``a.css`` -> ``./a.css``).

    Leaves absolute URLs, protocol-relative URLs, root-absolute paths and
    already-relative paths untouched so ken's resolver/classifier handle them
    correctly.
    """
    u = uri.strip()
    if (
        not u
        or u.startswith(("./", "../", "/", "~"))
        or "://" in u
        or u.startswith("//")
    ):
        return u
    return "./" + u


def _collapse(text: str | None) -> str | None:
    """Collapse internal whitespace/newlines in a selector list to spaces."""
    if not text:
        return None
    return " ".join(text.split())


def _css_doc(node: Node, src: bytes) -> str | None:
    """First content line of a preceding ``/* ... */`` comment sibling."""
    sib = node.prev_named_sibling
    if sib is None or sib.type != "comment":
        return None
    text = node_text(sib, src) or ""
    inner = text.removeprefix("/*").removesuffix("*/")
    for raw in inner.splitlines():
        line = raw.strip().lstrip("*").strip()
        if line:
            return line
    return None
