"""Query-time structural extraction (calls, class bases, wiring) via tree-sitter.

The indexer stores symbols and imports; these three richer signals — call
sites, inheritance clauses, and route/CLI/decorator wiring — are extracted on
demand by re-parsing the live file. ken-sized repos re-parse fast enough that
no persistence is required for v1; the resolution is precision-first so the
agent can trust what comes back.

Currently implemented for **Python**. Other languages return empty lists and
the calling tools say so explicitly rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

_PY_LANG = Language(tspython.language())
_PY_PARSER = Parser(_PY_LANG)

SUPPORTED = {"python"}


@dataclass
class CallSite:
    name: str          # the called identifier (last component of a.b.c -> c)
    line: int          # 1-based


@dataclass
class ClassBases:
    name: str
    bases: list[str]   # raw base identifiers (last component of dotted names)
    line: int


@dataclass
class WireSite:
    kind: str          # route | cli | env | config | decorator
    trigger: str       # the literal string ('/users/{id}', '--flag', 'KEN_TOKEN')
    decorator: str     # the decorator/callee dotted name (e.g. app.route)
    line: int          # 1-based line of the decorated def / reference


def _text(node: Node | None, src: bytes) -> str:
    if node is None:
        return ""
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _last_component(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1].strip()


def _callee_name(func_node: Node, src: bytes) -> str | None:
    """Resolve the called name from a `call` node's function field."""
    if func_node is None:
        return None
    if func_node.type == "identifier":
        return _text(func_node, src)
    if func_node.type == "attribute":
        attr = func_node.child_by_field_name("attribute")
        return _text(attr, src) if attr is not None else None
    return None


def extract_calls(source: bytes, language: str) -> list[CallSite]:
    if language not in SUPPORTED:
        return []
    tree = _PY_PARSER.parse(source)
    out: list[CallSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "call":
            name = _callee_name(node.child_by_field_name("function"), source)
            if name:
                out.append(CallSite(name=name, line=node.start_point[0] + 1))
        stack.extend(node.children)
    return out


def extract_bases(source: bytes, language: str) -> list[ClassBases]:
    if language not in SUPPORTED:
        return []
    tree = _PY_PARSER.parse(source)
    out: list[ClassBases] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "class_definition":
            name = _text(node.child_by_field_name("name"), source)
            supers = node.child_by_field_name("superclasses")
            bases: list[str] = []
            if supers is not None:
                for ch in supers.children:
                    if ch.type in ("identifier", "attribute"):
                        bases.append(_last_component(_text(ch, source)))
            if name:
                out.append(ClassBases(name=name, bases=bases, line=node.start_point[0] + 1))
        stack.extend(node.children)
    return out


# Decorators we recognise as runtime wiring, mapped to a trigger kind.
_ROUTE_ATTRS = {"route", "get", "post", "put", "patch", "delete", "websocket"}
_CLI_ATTRS = {"command", "group", "add_parser", "add_subparsers"}


def extract_wiring(source: bytes, language: str) -> list[WireSite]:
    if language not in SUPPORTED:
        return []
    tree = _PY_PARSER.parse(source)
    out: list[WireSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "decorated_definition":
            out.extend(_wiring_from_decorated(node, source))
        elif node.type == "call":
            out.extend(_wiring_from_env(node, source))
        elif node.type == "subscript":
            out.extend(_wiring_from_subscript(node, source))
        stack.extend(node.children)
    return out


def _wiring_from_subscript(node: Node, src: bytes) -> list[WireSite]:
    """Detect os.environ['KEY'] style config reads with a literal key."""
    value = node.child_by_field_name("value")
    dotted = _text(value, src)
    if _last_component(dotted) != "environ":
        return []
    sub = node.child_by_field_name("subscript")
    if sub is None or sub.type != "string":
        return []
    key = _text(sub, src).strip().strip("'\"").strip()
    if not key:
        return []
    return [WireSite("env", key, dotted, node.start_point[0] + 1)]


def _wiring_from_decorated(node: Node, src: bytes) -> list[WireSite]:
    defn = node.child_by_field_name("definition")
    line = (defn.start_point[0] + 1) if defn is not None else node.start_point[0] + 1
    out: list[WireSite] = []
    for ch in node.children:
        if ch.type != "decorator":
            continue
        inner = next((c for c in ch.children if c.type in ("call", "attribute", "identifier")), None)
        if inner is None:
            continue
        if inner.type == "call":
            callee = inner.child_by_field_name("function")
            dotted = _text(callee, src)
            attr = _last_component(dotted)
            literal = _first_string_arg(inner.child_by_field_name("arguments"), src)
            if attr in _ROUTE_ATTRS:
                out.append(WireSite("route", literal or dotted, dotted, line))
            elif attr in _CLI_ATTRS:
                out.append(WireSite("cli", literal or dotted, dotted, line))
            else:
                out.append(WireSite("decorator", literal or dotted, dotted, line))
        else:
            dotted = _text(inner, src)
            out.append(WireSite("decorator", dotted, dotted, line))
    return out


def _wiring_from_env(node: Node, src: bytes) -> list[WireSite]:
    """Detect os.environ / os.getenv style config reads with a literal key."""
    callee = node.child_by_field_name("function")
    dotted = _text(callee, src)
    if _last_component(dotted) not in ("getenv", "environ", "get"):
        return []
    if "environ" not in dotted and "getenv" not in dotted:
        return []
    key = _first_string_arg(node.child_by_field_name("arguments"), src)
    if not key:
        return []
    return [WireSite("env", key, dotted, node.start_point[0] + 1)]


def _first_string_arg(args: Node | None, src: bytes) -> str | None:
    if args is None:
        return None
    for ch in args.children:
        if ch.type == "string":
            raw = _text(ch, src)
            return raw.strip().strip("'\"").strip()
    return None
