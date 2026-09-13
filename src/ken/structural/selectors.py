"""User-facing selectors compiled to the same graph joins as catalogue rules."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .query import Clause, Pattern, parse_pattern

SELECTORS = {"class": "CLASS", "interface": "INTERFACE", "method": "CALLABLE", "function": "CALLABLE",
             "var_declaration": "STORAGE", "variable": "STORAGE", "parameter": "PARAMETER",
             "call": "CALL", "value": "VALUE", "collection": "COLLECTION", "entity": "_"}
RELATIONS = {"has_method": ("HAS_METHOD", "CALLABLE"), "has_parameter": ("HAS_PARAMETER", "PARAMETER"),
             "has_argument": ("ARGUMENT", "_"), "has_call": ("HAS_CALL", "CALL"),
             "has_field": ("HAS_FIELD", "STORAGE"), "returns": ("RETURNS", "_"),
             "reads": ("READS", "_"), "writes": ("WRITES", "_"), "calls": ("CALLS", "CALLABLE"),
             "used_by": ("CALLS", "CALLABLE")}
TOKEN = re.compile(r'''\s*(?:(?P<comment>\#[^\n]*)|(?P<regex>/(?:\\.|[^/\\\n])*/[ims]*)|(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<word>[@$]?[\w.\-]+)|(?P<symbol>[(){}\[\]:,;*]))''')


@dataclass
class Token:
    value: str
    kind: str


def compile_selectors(source: str) -> Pattern:
    # Triple clauses remain available for arbitrary relations and bounded paths.
    lines, triple_lines = [], []
    for line in source.splitlines():
        if re.match(r"\s*(require|optional|forbid|count|different|capability|pattern|scope)\s", line):
            triple_lines.append(line.rstrip().removesuffix(";"))
        else:
            lines.append(line)
    text = "\n".join(lines)
    tokens: list[Token] = []
    offset = 0
    while offset < len(text):
        if not text[offset:].strip():
            break
        match = TOKEN.match(text, offset)
        if not match:
            raise ValueError(f"invalid selector syntax near {text[offset:offset + 40]!r}")
        if match.lastgroup != "comment":
            tokens.append(Token(match[match.lastgroup or "symbol"], match.lastgroup or "symbol"))
        offset = match.end()
    p = Pattern("query")
    index = 0
    auto_id = 0

    def take(expected: str | None = None) -> Token:
        nonlocal index
        if index >= len(tokens):
            raise ValueError(f"expected {expected or 'token'}, reached end of query")
        token = tokens[index]
        index += 1
        if expected is not None and token.value != expected:
            raise ValueError(f"expected {expected!r}, got {token.value!r}")
        return token

    def peek(value: str) -> bool:
        return index < len(tokens) and tokens[index].value == value

    def literal() -> tuple[str, str]:
        token = take()
        if token.value == "[":
            items = []
            while not peek("]"):
                op, value = literal()
                if op != "=":
                    raise ValueError("type alternatives accept literal values")
                items.append(value)
                if not peek("]"):
                    take(",")
            take("]")
            if not items:
                raise ValueError("empty alternatives")
            return "=", "|".join(items)
        if token.kind == "regex":
            pattern, flags = token.value[1:].rsplit("/", 1)
            if len(pattern) > 512:
                raise ValueError("regular expressions are limited to 512 characters")
            expression = f"(?{flags}){pattern}" if flags else pattern
            from .query import _regex
            _regex(expression)
            return "regex", expression
        if token.kind == "string":
            import ast
            return "=", str(ast.literal_eval(token.value))
        return "=", token.value

    def selector(parent: str = "") -> None:
        nonlocal auto_id
        name = take().value
        take("(")
        attrs: list[tuple[str, str, str]] = []
        while not peek(")"):
            key = take().value
            take(":")
            op, value = literal()
            if value != "*":
                attrs.append((key, op, value))
            if not peek(")"):
                take(",")
        take(")")
        if peek("as"):
            take("as")
        if index < len(tokens) and tokens[index].kind == "word" and tokens[index].value not in SELECTORS and tokens[index].value not in RELATIONS:
            alias = take().value
            alias = alias if alias.startswith("$") else "$" + alias
        else:
            auto_id += 1
            alias = f"$_{auto_id}"
        if name in RELATIONS:
            if not parent:
                raise ValueError(f"{name} needs an enclosing selector")
            relation, kind = RELATIONS[name]
            if name == "has_parameter" and not any(k == "receiver" for k, _, _ in attrs):
                attrs.append(("receiver", "=", "false"))
            edge_attrs = []
            entity_attrs = []
            for key, op, value in attrs:
                if name == "has_argument" and key in {"pos", "name", "kind"}:
                    edge_attrs.append(("position" if key == "pos" else key, op, value))
                else:
                    entity_attrs.append((key, op, value))
            a, z = (alias, parent) if name == "used_by" else (parent, alias)
            p.clauses.append(Clause("require", a, relation, z, edge_attrs))
            p.clauses.append(Clause("require", alias, "ENTITY", kind, entity_attrs))
        elif name in SELECTORS:
            if parent:
                raise ValueError("nested selectors must name a relationship, e.g. has_method")
            if name == "var_declaration":
                attrs.append(("declared", "=", "true"))
            p.clauses.append(Clause("require", alias, "ENTITY", SELECTORS[name], attrs))
        elif name == "operation":
            p.clauses.append(Clause("require", alias, "OPERATION", "_", attrs))
        else:
            raise ValueError(f"unknown selector {name!r}; use entity(...) for generic entities")
        if peek("{"):
            take("{")
            while not peek("}"):
                selector(alias)
            take("}")
        if peek(";"):
            take(";")

    while index < len(tokens):
        selector()
    if triple_lines:
        extra = parse_pattern("require $_anchor ENTITY _\n" + "\n".join(triple_lines), validate_roles=False)
        p.clauses.extend(extra.clauses[1:])
        p.different = extra.different
        p.capabilities = extra.capabilities
        if extra.name != "query":
            p.name = extra.name
    if not p.clauses:
        raise ValueError("empty query")
    bound = {t for c in p.clauses if c.mode == "require" for t in (c.subject, c.object)}
    if any(a not in bound or b not in bound for a, b in p.different):
        raise ValueError("different requires roles bound by selectors or required clauses")
    return p


def parse_query(source: str) -> Pattern:
    if re.search(r"\b(?:" + "|".join([*SELECTORS, *RELATIONS, "operation"]) + r")\s*\(", source):
        return compile_selectors(source)
    return parse_pattern(source)
