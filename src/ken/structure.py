"""Language-agnostic structural extraction (calls, class bases, wiring).

The indexer stores symbols and imports; these three richer signals — call
sites, inheritance clauses, and decorator/annotation wiring — are extracted on
demand by re-parsing the live file with tree-sitter. ken-sized repos re-parse
fast enough that no persistence is required for v1.

Generic by design: a parser for **any** ``tree-sitter-language-pack`` grammar is
obtained via ``tree_sitter.Parser(get_language(name))`` (the same path the Dart
parser already uses), and callee/base names are pulled with grammar-driven node
specs plus a "rightmost identifier" heuristic that holds across languages. A
language with no explicit spec still gets a best-effort pass; the calling tools
report which languages produced results.
"""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node, Parser
from tree_sitter_language_pack import get_language

# Map ken language labels -> language-pack grammar names (identical except where
# noted). Anything here (or any pack grammar) can be parsed.
_GRAMMAR = {
    "python": "python", "javascript": "javascript", "typescript": "typescript",
    "rust": "rust", "go": "go", "java": "java", "c": "c", "dart": "dart",
}

_parsers: dict[str, Parser | None] = {}


def get_parser(language: str) -> Parser | None:
    """Cached tree-sitter parser for a language label (None if unavailable)."""
    if language not in _parsers:
        name = _GRAMMAR.get(language, language)
        try:
            _parsers[language] = Parser(get_language(name))
        except Exception:
            _parsers[language] = None
    return _parsers[language]


def supports(language: str | None) -> bool:
    return bool(language) and get_parser(language) is not None


@dataclass
class CallSite:
    name: str          # the called identifier (rightmost component of a.b.c -> c)
    line: int          # 1-based


@dataclass
class ClassBases:
    name: str
    bases: list[str]   # raw base identifiers (rightmost component of dotted names)
    line: int


@dataclass
class WireSite:
    kind: str          # route | cli | env | decorator
    trigger: str       # the literal string ('/users/{id}', '--flag', 'KEN_TOKEN')
    decorator: str     # the decorator/annotation/callee name
    line: int          # 1-based line of the decorated/annotated definition


# Call-expression node types per language. A call is a single node here (every
# grammar except Dart, handled specially below).
_CALL_TYPES = {
    "python": {"call"},
    "javascript": {"call_expression", "new_expression"},
    "typescript": {"call_expression", "new_expression"},
    "rust": {"call_expression", "macro_invocation"},
    "go": {"call_expression"},
    "java": {"method_invocation", "object_creation_expression"},
    "c": {"call_expression"},
}
# Generic fallback when a language has no explicit entry.
_CALL_HINT = ("call_expression", "call", "method_invocation", "invocation")
# Fields that point at the callee within a call node, in priority order.
_CALLEE_FIELDS = ("function", "constructor", "macro", "name", "type")


def _text(node: Node | None, src: bytes) -> str:
    if node is None:
        return ""
    return src[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _rightmost_identifier(node: Node | None, src: bytes) -> str | None:
    """Return the last identifier-like leaf under *node* (so a.b.c -> c)."""
    if node is None:
        return None
    found: list[str] = []
    stack = [node]
    # Collect identifier leaves; pick the one with the greatest start_byte.
    best: tuple[int, str] | None = None
    while stack:
        n = stack.pop()
        if n.child_count == 0:
            if n.type.endswith("identifier") or n.type in ("type_identifier", "field_identifier"):
                if best is None or n.start_byte > best[0]:
                    best = (n.start_byte, _text(n, src))
        else:
            stack.extend(n.children)
    return best[1] if best else None


def _call_types_for(language: str) -> set[str]:
    return _CALL_TYPES.get(language, set())


def extract_calls(source: bytes, language: str) -> list[CallSite]:
    parser = get_parser(language)
    if parser is None or not source:
        return []
    if language == "dart":
        return _extract_calls_dart(source, parser)
    tree = parser.parse(source)
    call_types = _call_types_for(language)
    out: list[CallSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        is_call = node.type in call_types if call_types else any(h in node.type for h in _CALL_HINT)
        if is_call:
            callee = None
            for field in _CALLEE_FIELDS:
                callee = node.child_by_field_name(field)
                if callee is not None:
                    break
            if callee is None:  # fallback: first named child that is not the args
                callee = next((c for c in node.children
                               if c.is_named and "argument" not in c.type), None)
            name = _rightmost_identifier(callee, source)
            if name:
                out.append(CallSite(name=name, line=node.start_point[0] + 1))
        stack.extend(node.children)
    return out


def _extract_calls_dart(source: bytes, parser: Parser) -> list[CallSite]:
    """Dart calls are `<expr> selector(argument_part)`, not a single node."""
    tree = parser.parse(source)
    out: list[CallSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        # An argument_part marks a call; the callee is the identifier immediately
        # to its left among the parent's children.
        if node.type == "selector" and any(c.type == "argument_part" for c in node.children):
            parent = node.parent
            if parent is not None:
                prev_name = None
                for c in parent.children:
                    if c == node:
                        break
                    nm = _rightmost_identifier(c, source) if c.is_named else None
                    if nm:
                        prev_name = nm
                if prev_name:
                    out.append(CallSite(name=prev_name, line=node.start_point[0] + 1))
        stack.extend(node.children)
    return out


# Class-definition node types and the fields/children that hold base types.
_CLASS_TYPES = {
    "python": {"class_definition"},
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration"},
    "java": {"class_declaration"},
    "dart": {"class_definition"},
}
_HERITAGE_FIELDS = ("superclasses", "superclass", "super_interfaces")
_HERITAGE_NODES = {"class_heritage", "extends_clause", "implements_clause",
                   "superclass", "super_interfaces"}


def extract_bases(source: bytes, language: str) -> list[ClassBases]:
    parser = get_parser(language)
    if parser is None or not source:
        return []
    class_types = _CLASS_TYPES.get(language)
    if not class_types:  # no class concept (rust/go/c) -> nothing to extract
        return []
    tree = parser.parse(source)
    out: list[ClassBases] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in class_types:
            name = _text(node.child_by_field_name("name"), source)
            bases = _collect_bases(node, source, name)
            if name:
                out.append(ClassBases(name=name, bases=bases, line=node.start_point[0] + 1))
        stack.extend(node.children)
    return out


def _collect_bases(class_node: Node, src: bytes, own_name: str) -> list[str]:
    containers: list[Node] = []
    for field in _HERITAGE_FIELDS:
        c = class_node.child_by_field_name(field)
        if c is not None:
            containers.append(c)
    for c in class_node.children:
        if c.type in _HERITAGE_NODES:
            containers.append(c)
    bases: list[str] = []
    seen = set()
    for container in containers:
        stack = [container]
        while stack:
            n = stack.pop()
            if n.type in ("identifier", "type_identifier", "scoped_type_identifier",
                          "constructor_type", "generic_type"):
                nm = _text(n, src).split("<")[0].rsplit(".", 1)[-1].rsplit("::", 1)[-1].strip()
                if nm and nm != own_name and nm not in seen:
                    seen.add(nm)
                    bases.append(nm)
                    continue
            stack.extend(n.children)
    return bases


# Decorator / annotation node types that may carry runtime wiring.
_DECORATOR_NODES = {"decorator", "annotation", "marker_annotation"}
# Matched case-insensitively so Flask `@app.route`, NestJS `@Get`, Spring
# `@GetMapping`, and TypeGraphQL `@Query`/`@Mutation` (the API surface of a
# GraphQL service) are all recognised as entrypoints.
_ROUTE_ATTRS = {"route", "get", "post", "put", "patch", "delete", "websocket",
                "getmapping", "postmapping", "requestmapping", "putmapping",
                "deletemapping", "patchmapping",
                "query", "mutation", "subscription"}
_CLI_ATTRS = {"command", "group", "add_parser", "add_subparsers"}
_CALLEE_NODE_TYPES = ("call", "call_expression", "attribute", "member_expression",
                      "identifier", "scoped_identifier")


def extract_wiring(source: bytes, language: str) -> list[WireSite]:
    parser = get_parser(language)
    if parser is None or not source:
        return []
    tree = parser.parse(source)
    out: list[WireSite] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in _DECORATOR_NODES:
            site = _wiring_from_decorator(node, source)
            if site is not None:
                out.append(site)
        elif node.type == "call":  # python os.getenv(...)
            out.extend(_wiring_from_env_call(node, source))
        elif node.type == "subscript":  # python os.environ['KEY']
            out.extend(_wiring_from_subscript(node, source))
        stack.extend(node.children)
    return out


def _is_def(node_type: str) -> bool:
    if node_type == "decorated_definition":
        return False
    return (
        node_type.endswith("definition")
        or node_type.endswith("declaration")
        or node_type in ("method_signature", "function_item")
    )


def _decorated_target_line(dec_node: Node) -> int:
    """Line of the *definition* a decorator/annotation applies to.

    Returns a line inside the target symbol (its name/def line, never the
    decorator line) so callers can bind it via ci_symbols line ranges.
    """
    parent = dec_node.parent
    if parent is None:
        return dec_node.start_point[0] + 1
    cands = [c for c in parent.children if _is_def(c.type)]
    after = [c for c in cands if c.start_byte >= dec_node.start_byte]
    target = after[0] if after else (cands[0] if cands else None)
    if target is None and parent.parent is not None:  # e.g. java annotation under modifiers
        gcands = [c for c in parent.parent.children if _is_def(c.type)]
        target = gcands[0] if gcands else None
    if target is None:
        return dec_node.start_point[0] + 1
    name = target.child_by_field_name("name")
    return (name or target).start_point[0] + 1


def _wiring_from_decorator(node: Node, src: bytes) -> WireSite | None:
    line = _decorated_target_line(node)
    # Find the callable/name + first string literal inside the decorator.
    name_node = next((c for c in node.children if c.type in _CALLEE_NODE_TYPES), None)
    if name_node is None:  # java annotation: identifier is a field
        name_node = node.child_by_field_name("name") or next(
            (c for c in node.children if c.type.endswith("identifier")), None)
    # For a call decorator (@Get('/x')) the callee is the function being called.
    if name_node is not None and name_node.type in ("call", "call_expression"):
        name_node = name_node.child_by_field_name("function") or name_node
    dotted = _text(name_node, src) if name_node is not None else _text(node, src).lstrip("@")
    dotted = dotted.rsplit("(", 1)[0].strip()
    attr = dotted.rsplit(".", 1)[-1].strip()
    literal = _first_string(node, src)
    if attr.lower() in _ROUTE_ATTRS:
        return WireSite("route", literal or dotted, dotted, line)
    if attr.lower() in _CLI_ATTRS:
        return WireSite("cli", literal or dotted, dotted, line)
    return WireSite("decorator", literal or attr or dotted, attr or dotted, line)


def _wiring_from_env_call(node: Node, src: bytes) -> list[WireSite]:
    dotted = _text(node.child_by_field_name("function"), src)
    last = dotted.rsplit(".", 1)[-1]
    if last not in ("getenv", "environ", "get") or ("environ" not in dotted and "getenv" not in dotted):
        return []
    key = _first_string(node.child_by_field_name("arguments"), src)
    return [WireSite("env", key, dotted, node.start_point[0] + 1)] if key else []


def _wiring_from_subscript(node: Node, src: bytes) -> list[WireSite]:
    value = node.child_by_field_name("value")
    dotted = _text(value, src)
    if dotted.rsplit(".", 1)[-1] != "environ":
        return []
    sub = node.child_by_field_name("subscript")
    if sub is None or sub.type != "string":
        return []
    key = _text(sub, src).strip().strip("'\"").strip()
    return [WireSite("env", key, dotted, node.start_point[0] + 1)] if key else []


def _first_string(node: Node | None, src: bytes) -> str | None:
    if node is None:
        return None
    stack = [node]
    best: tuple[int, str] | None = None
    while stack:
        n = stack.pop()
        if n.type in ("string", "string_literal", "interpreted_string_literal", "raw_string_literal"):
            val = _text(n, src).strip().strip("'\"`").strip()
            if val and (best is None or n.start_byte < best[0]):
                best = (n.start_byte, val)
        stack.extend(n.children)
    return best[1] if best else None
