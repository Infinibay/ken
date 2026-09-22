"""Read-only syntax values and bounded tree navigation over numeric vectors."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np

from ken.common_ast.kinds import NATIVE
from ken.common_ast.kinds import role as canonical_role
from ken.structural.frontend import ASSIGNMENTS, CALLS, FUNCTIONS, MEMBERS, TYPES

from ..values import Unknown, identity, is_unknown
from ..syntax_schema import SYNTAX_PROPERTIES as PROPERTIES

COMPARISONS = {
    "==",
    "!=",
    "===",
    "!==",
    "<",
    ">",
    "<=",
    ">=",
    "in",
    "is",
    "not in",
    "is not",
}
OPERATORS = COMPARISONS | {
    "+",
    "-",
    "*",
    "/",
    "//",
    "%",
    "**",
    "=",
    "+=",
    "-=",
    "*=",
    "/=",
    "&&",
    "||",
    "and",
    "or",
    "not",
    "!",
    "&",
    "|",
    "^",
    "~",
    "<<",
    ">>",
    "??",
    ":=",
}
def classification(native):
    if native in NATIVE:
        return NATIVE[native]
    if native in TYPES:
        return "type_declaration", "declaration"
    if native in FUNCTIONS:
        return "callable", "declaration"
    if native in CALLS:
        return "call", "expression"
    if native in ASSIGNMENTS:
        return "assignment", "expression"
    if native in MEMBERS:
        return "member", "expression"
    if native in {
        "binary_expression",
        "binary_operator",
        "boolean_operator",
        "comparison_operator",
    }:
        return "binary", "expression"
    if native in {"unary_expression", "unary_operator", "not_operator"}:
        return "unary", "expression"
    return "opaque", "opaque"


@dataclass(frozen=True, slots=True)
class SyntaxValue:
    unit: int
    revision: str
    index: int
    tree: SyntaxTree = field(compare=False, hash=False, repr=False)

    def get(self, name):
        return self.tree.property(self.index, name)

    @property
    def local_id(self):
        return f"{self.tree.path}::syntax:{self.index}:{self.get('start_byte')}:{self.get('end_byte')}:{self.get('native_kind')}"

    def record(self):
        return {
            key: self.get(key)
            for key in (
                "path",
                "language",
                "native_kind",
                "kind",
                "start_byte",
                "end_byte",
                "line",
            )
        }


def result_key(value):
    """Set identity without retaining file buffers through nested values."""
    if isinstance(value, SyntaxValue):
        return ("SyntaxValue", value.local_id)
    if isinstance(value, tuple):
        return ("Tuple", tuple(result_key(v) for v in value))
    return identity(value)


def contains_unknown(value):
    return (
        is_unknown(value)
        or isinstance(value, tuple)
        and any(map(contains_unknown, value))
    )


class SyntaxTree:
    def __init__(self, unit, path, language, revision, source, columns, dictionary):
        self.unit, self.path, self.language, self.revision = (
            unit,
            path,
            language,
            revision,
        )
        self.source, self.columns, self.dictionary = source, columns, dictionary
        (
            self.kind,
            self.role,
            self.parent,
            self.end,
            self.start_byte,
            self.end_byte,
            self.flags,
        ) = columns
        self.lines = np.flatnonzero(np.frombuffer(source, dtype="u1") == 10)
        self.postings = {}

    def positions(self, kinds):
        """Reuse a per-file posting list across many overlapping subtrees."""
        key = frozenset(kinds)
        if key not in self.postings:
            self.postings[key] = np.flatnonzero(
                ((self.flags & 1) != 0) & np.isin(self.kind, tuple(key))
            ).astype("<u4")
        return self.postings[key]

    def value(self, index):
        return SyntaxValue(self.unit, self.revision, int(index), self)

    def children(self, node, *, named=True):
        child = node + 1
        while child < self.end[node]:
            if not named or self.flags[child] & 1:
                yield child
            child = int(self.end[child])

    def subtree(self, node, *, include_root=False):
        for child in range(node if include_root else node + 1, int(self.end[node])):
            if self.flags[child] & 1:
                yield child

    def spelling(self, node):
        return self.source[self.start_byte[node] : self.end_byte[node]].decode(
            "utf-8", "replace"
        )

    def native(self, node):
        return self.dictionary.words[self.kind[node]]

    def operator(self, node):
        tokens = [
            self.native(c)
            for c in self.children(node, named=False)
            if not self.flags[c] & 1 and self.native(c) in OPERATORS
        ]
        return {"&&": "and", "||": "or", "!": "not", ":=": "="}.get(
            " ".join(tokens), " ".join(tokens)
        )

    def classified(self, node):
        kind, category = classification(self.native(node))
        if kind == "binary" and self.operator(node) in COMPARISONS:
            kind = "compare"
        return kind, category

    def property(self, node, name):
        if name == "path":
            return self.path
        if name == "language":
            return self.language
        if name == "start_byte":
            return int(self.start_byte[node])
        if name == "end_byte":
            return int(self.end_byte[node])
        if name == "line":
            return bisect_right(self.lines, int(self.start_byte[node]) - 1) + 1
        if name == "native_kind":
            return self.native(node)
        if name == "operator":
            return self.operator(node)
        kind, category = self.classified(node)
        if name == "kind":
            return kind
        if name == "category":
            return category
        if name == "normalized":
            return category != "opaque"
        if name == "role":
            parent = int(self.parent[node])
            return (
                canonical_role(
                    self.classified(parent)[0], self.dictionary.words[self.role[node]]
                )
                if parent >= 0
                else ""
            )
        if name == "name":
            if kind == "identifier":
                return self.spelling(node)
            if kind == "module":
                return self.path
            names = [
                c
                for c in self.children(node)
                if self.dictionary.words[self.role[c]] == "name"
            ]
            return self.spelling(names[0]) if len(names) == 1 else ""
        if name == "text":
            return (
                self.spelling(node)
                if kind == "literal" or not any(self.children(node))
                else ""
            )
        if name == "type_kind":
            if kind != "literal":
                return Unknown("type_resolution_required")
            native, text = self.native(node), self.spelling(node)
            if text in ("true", "false", "True", "False"):
                return "bool"
            if text in ("None", "null", "nil"):
                return "null"
            if "char" in native or "rune" in native:
                return "char"
            if "string" in native:
                return "str"
            if any(n in native for n in ("float", "real")):
                return "float"
            if native in ("number", "number_literal"):
                spelling = text.lower().replace("_", "")
                floating = "." in spelling or (
                    "p" in spelling
                    if spelling.startswith("0x")
                    else "e" in spelling and not spelling.startswith(("0b", "0o"))
                )
                return "float" if floating else "int"
            if "integer" in native or native == "int_literal":
                return "int"
            return Unknown("literal_type_unavailable")
        return Unknown("syntax_property_unavailable:" + name)
