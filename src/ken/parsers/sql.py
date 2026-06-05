"""SQL (DDL) symbol extractor.

The SQL grammar ships inside ``tree-sitter-language-pack`` rather than a
standalone wheel, so we pull the ``Language`` from there (same as Dart).

SQL is a schema/DSL language: there is **no module/import system** in the
standard ``CREATE`` DDL, so ``ParsedFile.imports`` is always empty. The
value ken gets from SQL is the *symbol table* of defined database objects
(tables, views, functions, …), which feed search / outline / co-change.

Grammar shape worth knowing:

* The tree is ``program`` → ``statement`` → a ``create_*`` / ``alter_*``
  node. Each ``statement`` is followed by a sibling ``;`` token.
* The defined object's name lives in an ``object_reference`` child that
  exposes a ``name`` field and an optional ``schema`` field
  (``CREATE TABLE myschema.orders`` → schema=myschema, name=orders).
* Two statements name their object with a bare leading ``identifier``
  instead of an ``object_reference``: ``create_index`` (the index name,
  which precedes the ``ON <table>`` object_reference) and
  ``create_schema``. Those are special-cased.
* Comments are ``comment`` (``-- line``) and ``marginalia`` (``/* block */``)
  nodes that sit as siblings *before* the ``statement`` wrapper.
"""

from __future__ import annotations

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

from ken.parsers._helpers import node_text
from ken.parsers.types import ParsedFile, ParsedSymbol

_PARSER = Parser(get_language("sql"))

# create_* node type → (ken kind, where the name comes from).
# "ref"   = the object's name is in an ``object_reference`` child.
# "ident" = the object's name is a bare leading ``identifier`` child.
_DEFINITIONS: dict[str, tuple[str, str]] = {
    "create_table": ("table", "ref"),
    "create_view": ("view", "ref"),
    "create_materialized_view": ("view", "ref"),
    "create_function": ("function", "ref"),
    "create_procedure": ("procedure", "ref"),
    "create_trigger": ("trigger", "ref"),
    "create_type": ("type", "ref"),
    "create_sequence": ("sequence", "ref"),
    "create_domain": ("type", "ref"),
    "create_index": ("index", "ident"),
    "create_schema": ("schema", "ident"),
}

_COMMENT_TYPES = {"comment", "marginalia"}


def parse_sql_file(source: bytes, path_hint: str) -> ParsedFile:  # noqa: ARG001
    tree = _PARSER.parse(source)
    out = ParsedFile()
    for stmt in tree.root_node.children:
        if stmt.type != "statement":
            continue
        defn = next((c for c in stmt.named_children if c.type in _DEFINITIONS), None)
        if defn is not None:
            _emit(defn, stmt, source, out)
    return out


def _emit(node: Node, stmt: Node, src: bytes, out: ParsedFile) -> None:
    kind, where = _DEFINITIONS[node.type]
    name, qualname = _name_of(node, src, where)
    if not name:
        return
    out.symbols.append(
        ParsedSymbol(
            kind=kind,
            name=name,
            qualname=qualname,
            line_start=stmt.start_point[0] + 1,
            line_end=stmt.end_point[0] + 1,
            docstring=_sql_doc(stmt, src),
        )
    )


def _name_of(node: Node, src: bytes, where: str) -> tuple[str | None, str | None]:
    """Return ``(name, qualname)`` for a create_* node.

    ``qualname`` carries the schema prefix when present
    (``myschema.orders``); ``name`` is the bare object name used for grep.
    """
    if where == "ident":
        ident = next((c for c in node.named_children if c.type == "identifier"), None)
        text = node_text(ident, src) if ident is not None else None
        return text, text
    ref = next((c for c in node.named_children if c.type == "object_reference"), None)
    if ref is None:
        return None, None
    name = node_text(ref.child_by_field_name("name"), src)
    schema = node_text(ref.child_by_field_name("schema"), src)
    if not name:
        return None, None
    return name, f"{schema}.{name}" if schema else name


def _sql_doc(stmt: Node, src: bytes) -> str | None:
    """First content line of the comment block immediately preceding *stmt*."""
    sib = stmt.prev_named_sibling
    collected: list[str] = []
    while sib is not None and sib.type in _COMMENT_TYPES:
        collected.append(node_text(sib, src) or "")
        sib = sib.prev_named_sibling
    collected.reverse()
    for raw in collected:
        line = raw.strip()
        if line.startswith("--"):
            line = line.lstrip("-").strip()
        elif line.startswith("/*"):
            line = line.removeprefix("/*").removesuffix("*/").strip().lstrip("*").strip()
        if line:
            return line
    return None
