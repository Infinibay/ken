"""Pratt expressions and contextual matchers; no declaration or BODY dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import Expr, Expression, SourceExpr
from .lexer import ParseError

if TYPE_CHECKING:
    from .parser import Parser

from .vocabulary import QUERY_BP, SOURCE_BP


def point(parser: Parser) -> Expr:
    start = parser.lexer.peek().span
    role = parser.role()
    parser.expect(".")
    point = parser.ident()
    if point not in {
        "before",
        "after",
        "after_normal",
        "after_exceptional",
        "entry",
        "exit",
    }:
        parser.fail("invalid point accessor")
    return Expr("member", parser.span(start), point, (Expr("role", start, role),))


def matcher(parser: Parser) -> Expr:
    if parser.peek() == "/":
        token = parser.lexer.regex()
        parser.last = token.span
        return Expr("regex", token.span, token.text)
    # Generic source types are unambiguous here; '<' in comparisons belongs
    # to a parenthesized query expression, as in the grammar's matcher rule.
    if parser.lexer.peek().kind == "IDENT":
        saved = parser.lexer.peek()
        mark = parser.mark()
        name = parser.qualified()
        if parser.accept("<"):
            args: list[Expr] = [parser.type_argument()]
            while parser.accept(","):
                args.append(parser.type_argument())
            parser.expect(">")
            return Expr("source_type", parser.span(saved.span), name, tuple(args))
        parser.reset(mark)
    result = parser.expr()
    assert isinstance(result, Expr)
    return result


def type_argument(parser: Parser) -> Expr:
    start = parser.lexer.peek().span
    if parser.peek() in ("_", "..."):
        token = parser.take()
        return Expr("wildcard", token.span, token.text)
    if parser.accept("("):
        args: list[Expr] = []
        if parser.peek() != ")":
            args.append(parser.type_argument())
            while parser.accept(","):
                args.append(parser.type_argument())
        parser.expect(")")
        parser.expect("->")
        args.append(parser.type_argument())
        return Expr("function_type", parser.span(start), args=tuple(args))
    name = parser.qualified()
    type_args: list[Expr] = []
    if parser.accept("<"):
        type_args.append(parser.type_argument())
        while parser.accept(","):
            type_args.append(parser.type_argument())
        parser.expect(">")
    return Expr("source_type", parser.span(start), name, tuple(type_args))


def arguments(parser: Parser, named_only: bool = False) -> tuple[Expr, ...]:
    parser.expect("(")
    args: list[Expr] = []
    if parser.peek() != ")":
        while True:
            name = ""
            if parser.lexer.peek().kind == "IDENT":
                mark = parser.mark()
                saved = parser.take()
                if parser.accept(":"):
                    name = saved.text
                else:
                    parser.reset(mark)
            if named_only and not name:
                parser.fail("use requires named arguments")
            value = parser.expr(min_bp=31)
            assert isinstance(value, Expr)
            args.append(Expr("argument", value.span, name, (value,)))
            if not parser.accept(","):
                break
    parser.expect(")")
    return tuple(args)


def _expr(parser: Parser, source: bool, min_bp: int) -> Expression:
    token = parser.take()

    def node(
        kind: str, value: str = "", args: tuple[Expression, ...] = ()
    ) -> Expression:
        if source:
            return SourceExpr(kind, parser.span(token.span), value, args)
        assert all(isinstance(a, Expr) for a in args)
        return Expr(
            kind,
            parser.span(token.span),
            value,
            tuple(a for a in args if isinstance(a, Expr)),
        )

    if token.text in ("not", "+", "-") or source and token.text in ("~", "++", "--"):
        left = node("unary", token.text, (parser.expr(source, 80),))
    elif token.kind in ("STRING", "INTEGER", "FLOAT") or token.text in (
        "true",
        "false",
        "null",
        "undefined",
    ):
        left = node("literal", token.text)
    elif token.kind == "ROLE":
        left = node("role", token.text[1:])
    elif token.text == "_":
        left = node("wildcard")
    elif token.text == "(":
        left = parser.expr(source)
        parser.expect(")")
    elif token.text == "[" and not source:
        elements: list[Expression] = []
        if parser.peek() != "]":
            elements.append(parser.expr(min_bp=31))
            while parser.accept(","):
                elements.append(parser.expr(min_bp=31))
        parser.expect("]")
        left = node("list", args=tuple(elements))
    elif (
        token.text
        in {"exists", "forall", "count", "sum", "sum_by", "min", "max", "avg"}
        and not source
    ):
        parser.expect("(")
        params = parser.parameters("|")
        if not params:
            parser.fail("quantifier requires a finite domain")
        parser.expect("|")
        formula = parser.expr()
        assert isinstance(formula, Expr)
        parts = [formula]
        if token.text != "exists":
            parser.expect("|")
            projection = (
                parser.expr() if token.text == "forall" else parser.expr(min_bp=31)
            )
            assert isinstance(projection, Expr)
            parts.append(projection)
        parser.expect(")")
        left = Expr(
            "quantifier" if token.text in ("exists", "forall") else "aggregate",
            parser.span(token.span),
            token.text,
            tuple(parts),
            params,
        )
    elif source and token.text == "new":
        role = parser.role()
        left = node("new", role, parser.arguments())
    elif token.kind == "IDENT":
        names = [token.text]
        while parser.accept("."):
            names.append(parser.ident())
        name = ".".join(names)
        if parser.peek() == "(":
            left = node("call", name, parser.arguments())
        elif source:
            raise ParseError(
                "source expressions require a role or application", token.span
            )
        else:
            left = node("name", name)
    else:
        raise ParseError(f"expected expression, got {token.text!r}", token.span)
    compared = False
    while True:
        op = parser.peek()
        if op == ".":
            parser.take()
            if parser.peek().startswith("$"):
                # ``$place.$field``: the member the pattern's own declaration role
                # names, so a query reads a member without fixing its spelling.
                declaration = parser.lexer.peek().span
                field = parser.role()
                left = node(
                    "member", "", (left, Expr("role", parser.span(declaration), field))
                )
                continue
            member = parser.ident()
            args: tuple[Expression, ...] = (left,)
            if not source and parser.peek() == "(":
                args += parser.arguments()
            left = node("member", member, args)
            continue
        if source and op == "[":
            parser.take()
            index = parser.expr(True)
            parser.expect("]")
            left = node("index", args=(left, index))
            continue
        if source and op in ("++", "--"):
            parser.take()
            left = node("postfix", op, (left,))
            break
        # Keep > tokens separate for nested generic types. Combine shifts
        # only in source expressions and only when byte-adjacent.
        if source and op in ("<", ">"):
            at = parser.lexer.pos
            if at < len(parser.lexer.text) and parser.lexer.text[at] == op:
                op += op
        if op == "not":
            # ``$key not in $pool``: the negated membership test. The lexer emits
            # ``not`` and ``in`` as two separate words, so the pair is folded here
            # into the one operator the condition vocabulary already reads, at the
            # comparison precedence ``in`` has on its own.
            token = parser.take()
            if parser.peek() != "in":
                raise ParseError("expected 'in' after 'not'", token.span)
            parser.take()
            if compared:
                parser.fail("comparisons cannot be chained")
            compared = True
            left = node("binary", "not in", (left, parser.expr(source, 31)))
            continue
        bp = (SOURCE_BP if source else QUERY_BP).get(op, -1)
        if bp < min_bp:
            break
        if bp == 30 and compared:
            parser.fail("comparisons cannot be chained")
        compared |= bp == 30
        parser.take()
        if op in ("<<", ">>"):
            parser.expect(op[0])
        if op == "matches" and parser.peek() == "/":
            regex = parser.lexer.regex()
            parser.last = regex.span
            right: Expression = Expr("regex", regex.span, regex.text)
        else:
            right = parser.expr(source, bp if op == "**" else bp + 1)
        left = node("binary", op, (left, right))
    return left
