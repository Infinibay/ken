"""Recursive descent declarations and Pratt expressions for the KQL 2 syntax."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import NoReturn

from . import body_parser, call_parser, clause_parser, expression_parser
from .ast import (
    Clause,
    Declaration,
    Expr,
    Expression,
    File,
    Parameter,
    Span,
    TypeName,
)
from .lexer import Lexer, ParseError, Token
from .vocabulary import RESERVED


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Speculative lookahead, including the already tokenized next token."""

    position: int
    lookahead: Token
    last: Span


class Parser:
    def __init__(
        self,
        text: str,
        source: str = "<query>",
        *,
        max_depth: int = 96,
        max_bytes: int = 2_000_000,
    ):
        self.lexer = Lexer(text, source, max_bytes=max_bytes)
        self.last = Span(source, 0, 0)
        self.depth, self.max_depth = 0, max_depth

    def peek(self) -> str:
        return self.lexer.peek().text

    def take(self) -> Token:
        token = self.lexer.take()
        self.last = token.span
        return token

    def accept(self, text: str) -> bool:
        if self.peek() == text:
            self.take()
            return True
        return False

    def expect(self, text: str) -> Token:
        token = self.take()
        if token.text != text:
            raise ParseError(f"expected {text!r}, got {token.text!r}", token.span)
        return token

    def token(self, kind: str) -> Token:
        token = self.take()
        if token.kind != kind:
            raise ParseError(f"expected {kind}, got {token.text!r}", token.span)
        return token

    def ident(self, *, declaration: bool = False) -> str:
        token = self.token("IDENT")
        if declaration and token.text in RESERVED - {"step"}:
            raise ParseError("reserved declaration name", token.span)
        return token.text

    def role(self) -> str:
        return self.token("ROLE").text[1:]

    def qualified(self) -> str:
        names = [self.ident()]
        while self.accept("."):
            names.append(self.ident())
        return ".".join(names)

    def span(self, start: Span) -> Span:
        return Span(start.source, start.start, self.last.end)

    def fail(self, message: str) -> NoReturn:
        raise ParseError(message, self.lexer.peek().span)

    def enter(self) -> None:
        self.depth += 1
        if self.depth > self.max_depth:
            raise ParseError(
                "syntax nesting limit exceeded",
                self.lexer.peek().span,
                "resource_limit",
            )

    def parse(self) -> File:
        start = self.expect("language").span
        dialect = json.loads(self.token("STRING").text)
        if dialect != "kql/2":
            raise ParseError(
                "expected language kql/2", self.last, "unsupported_dialect"
            )
        self.expect(";")
        self.expect("module")
        module = self.qualified()
        self.expect(";")
        imports: list[str] = []
        while self.accept("import"):
            imports.append(self.qualified())
            self.expect(";")
        declarations: list[Declaration] = []
        while self.lexer.peek().kind != "EOF":
            declarations.append(self.declaration())
        self.take()
        return File(
            dialect, module, tuple(imports), tuple(declarations), self.span(start)
        )

    def qtype(self) -> TypeName:
        self.enter()
        try:
            name = self.qualified()
            args: list[TypeName] = []
            if self.accept("<"):
                args.append(self.qtype())
                while self.accept(","):
                    args.append(self.qtype())
                self.expect(">")
            return TypeName(name, tuple(args))
        finally:
            self.depth -= 1

    def parameters(self, end: str, directional: bool = False) -> tuple[Parameter, ...]:
        params: list[Parameter] = []
        if self.peek() != end:
            while True:
                direction = "relation"
                if directional:
                    direction = self.take().text
                    if direction not in ("in", "out"):
                        self.fail("pattern parameter requires in or out")
                params.append(Parameter(self.qtype(), self.role(), direction))
                if not self.accept(","):
                    break
        return tuple(params)

    def declaration(self, signature: bool = False) -> Declaration:
        start = self.take()
        kind = start.text
        if kind not in {"pattern", "predicate", "query", "enum", "signature", "model"}:
            raise ParseError("expected declaration", start.span)
        name = self.ident(declaration=True)
        params: tuple[Parameter, ...] = ()
        generics: list[tuple[str, str]] = []
        if kind == "pattern" and self.accept("<"):
            while True:
                generic = self.ident(declaration=True)
                self.expect(":")
                generics.append((generic, self.qualified()))
                if not self.accept(","):
                    break
            self.expect(">")
        if kind in ("pattern", "predicate"):
            self.expect("(")
            params = self.parameters(")", kind == "pattern")
            self.expect(")")
        if signature:
            if kind != "predicate":
                self.fail("signature members must be predicates")
            self.expect(";")
            return Declaration(kind, name, self.span(start.span), parameters=params)
        if kind == "predicate":
            self.expect("{")
            formula = self.expr()
            assert isinstance(formula, Expr)
            self.expect("}")
            return Declaration(
                kind, name, self.span(start.span), parameters=params, formula=formula
            )
        if kind == "enum":
            self.expect("{")
            values = [self.ident()]
            while self.accept(","):
                values.append(self.ident())
            self.expect("}")
            return Declaration(kind, name, self.span(start.span), values=tuple(values))
        if kind in ("signature", "model"):
            implements = ""
            if kind == "model":
                self.expect("implements")
                implements = self.qualified()
            self.expect("{")
            members: list[Declaration] = []
            while self.peek() != "}":
                if self.peek() != "predicate":
                    self.fail("expected predicate member")
                members.append(self.declaration(signature=kind == "signature"))
            self.expect("}")
            return Declaration(
                kind,
                name,
                self.span(start.span),
                members=tuple(members),
                implements=implements,
            )
        clauses = self.block("query" if kind == "query" else "constraint")
        return Declaration(
            kind, name, self.span(start.span), params, tuple(generics), clauses
        )

    def block(self, mode: str = "constraint") -> tuple[Clause, ...]:
        self.enter()
        try:
            self.expect("{")
            clauses: list[Clause] = []
            while self.peek() != "}":
                if self.lexer.peek().kind == "EOF":
                    self.fail("unterminated block")
                clauses.append(self.clause(mode))
            self.expect("}")
            if mode == "query":
                kinds = [c.kind for c in clauses]
                if kinds.count("select") != 1:
                    self.fail("query requires exactly one select")
                tail = kinds[kinds.index("select") + 1 :]
                if tail not in ([], ["order"], ["limit"], ["order", "limit"]):
                    self.fail("only order and limit may follow select")
            return tuple(clauses)
        finally:
            self.depth -= 1

    def clause(self, mode: str) -> Clause:
        start = self.lexer.peek().span
        clause = self._clause(mode)
        return replace(clause, span=self.span(start))

    def _clause(self, mode: str) -> Clause:
        return clause_parser.parse_clause(self, mode)

    def _char_offset(self, byte: int) -> int:
        from bisect import bisect_left

        return bisect_left(self.lexer.offsets, byte)

    def mark(self) -> Checkpoint:
        """Save lookahead without converting UTF-8 offsets or re-lexing it later."""
        lookahead = self.lexer.peek()
        return Checkpoint(self.lexer.pos, lookahead, self.last)

    def reset(self, mark: Checkpoint | int) -> None:
        """Restore speculation, or rewind a consumed BODY token by char offset."""
        if isinstance(mark, Checkpoint):
            self.lexer.pos = mark.position
            self.lexer.cached = mark.lookahead
            self.last = mark.last
            return
        self.lexer.pos = mark
        self.lexer.cached = None

    def alias(self) -> str:
        return self.role() if self.accept("as") else ""

    def point(self) -> Expr:
        return expression_parser.point(self)

    def matcher(self) -> Expr:
        return expression_parser.matcher(self)

    def type_argument(self) -> Expr:
        return expression_parser.type_argument(self)

    def arguments(self, named_only: bool = False) -> tuple[Expr, ...]:
        return expression_parser.arguments(self, named_only)

    def expr(self, source: bool = False, min_bp: int = 0) -> Expression:
        self.enter()
        try:
            return self._expr(source, min_bp)
        finally:
            self.depth -= 1

    def _expr(self, source: bool, min_bp: int) -> Expression:
        return expression_parser._expr(self, source, min_bp)

    def call(self) -> Clause:
        return call_parser.call(self)

    def argument(self) -> Clause:
        return call_parser.argument(self)

    def construct(self) -> Clause:
        return call_parser.construct(self)

    def body_clause(self, word: str, start: Span) -> Clause:
        return body_parser.parse_body_clause(self, word, start)


def parse(
    text: str,
    source_id: str = "<query>",
    *,
    max_depth: int = 96,
    max_bytes: int = 2_000_000,
) -> File:
    """Parse syntax only. Compilation must validate names, types and capabilities."""
    parser = Parser(text, source_id, max_depth=max_depth, max_bytes=max_bytes)
    try:
        return parser.parse()
    except RecursionError as exc:
        raise ParseError(
            "syntax nesting limit exceeded", parser.lexer.peek().span, "resource_limit"
        ) from exc
