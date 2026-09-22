"""Query and constraint productions with explicit contextual dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import Clause, Expr, Expression, Span

if TYPE_CHECKING:
    from .parser import Parser

from collections.abc import Callable, Mapping
from dataclasses import replace
from types import MappingProxyType

from .vocabulary import SELECTORS


def parse_usages(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    if mode == "body":
        parser.fail("usages selects consumers outside BODY")
    parser.expect("of")
    value = parser.role()
    parser.expect("as")
    usage = parser.role()
    return Clause(
        "source_usages",
        parser.span(start),
        name=value,
        role=usage,
        blocks=(parser.block(),),
    )


def parse_require(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    if mode == "body":
        parser.fail("source requirements belong outside BODY")
    quantifier = parser.take().text
    if quantifier not in ("exists", "every", "one"):
        parser.fail("require accepts exists, every or one")
    declaration = parser.take().text
    if quantifier == "one":
        if declaration not in ("allocation", "dispatch"):
            parser.fail("one quantifies the resolved allocation or dispatch count")
    elif declaration != "constructor":
        parser.fail("quantified source declarations currently support constructor")
    parser.expect("of")
    owner = parser.role()
    witness = ""
    if parser.accept("named"):
        if quantifier != "one" or declaration != "dispatch":
            parser.fail("named qualifies only one dispatch")
        witness = parser.role()
    if quantifier == "exists" or quantifier == "one":
        parser.expect(";")
        properties: tuple[Clause, ...] = ()
    else:
        properties = parser.block()
    return Clause(
        "source_require",
        parser.span(start),
        name=declaration,
        role=owner,
        flags=(quantifier, witness),
        blocks=(properties,),
    )


def parse_initializer(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    parser.expect("{")
    if parser.peek() == "construct":
        expression = parser.construct()
    elif parser.accept("call"):
        expression = Clause("call", start, role=parser.role(), blocks=(parser.block(),))
    else:
        parser.fail("declaration initializer requires construct or call expression")
    alias = parser.alias()
    parser.expect(";")
    parser.expect("}")
    return Clause(
        "declaration_initializer",
        parser.span(start),
        blocks=((replace(expression, alias=alias),),),
    )


def parse_edge(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    name = parser.ident()
    parser.expect("(")
    subject = parser.expr(min_bp=31)
    parser.expect(",")
    target = parser.expr(min_bp=31)
    parser.expect(")")
    properties = parser.block() if parser.peek() == "{" else ()
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        word,
        parser.span(start),
        name=name,
        expressions=(subject, target),
        blocks=(properties,),
        alias=alias,
    )


def parse_tally(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    parser.expect("distinct")
    role = parser.role()
    comparison = parser.take().text
    if comparison not in ("==", "<=", ">=", "<", ">"):
        parser.fail("tally requires a count comparison")
    count = parser.token("INTEGER").text
    body = parser.block()
    parser.expect(";")
    return Clause(
        word,
        parser.span(start),
        role=role,
        name=comparison,
        flags=(count,),
        blocks=(body,),
    )


def parse_at_least(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    # ``at least 2 distinct $action { ... }``: an existential cardinality
    # requirement over the solutions of the nested block, read as the count of
    # distinct values the named role takes. It lowers to the same counting node
    # the older ``tally distinct`` spelling produces.
    parser.expect("least")
    count = parser.token("INTEGER").text
    parser.expect("distinct")
    role = parser.role()
    body = parser.block()
    parser.expect(";")
    return Clause(
        "count",
        parser.span(start),
        role=role,
        name=">=",
        flags=(count,),
        blocks=(body,),
    )


def parse_from(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    params = parser.parameters(";")
    if not params:
        parser.fail("from requires a domain")
    parser.expect(";")
    return Clause(word, parser.span(start), parameters=params)


def parse_condition(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    role = parser.role() if word == "bind" else ""
    if word == "bind":
        parser.expect("=")
    value = parser.expr()
    parser.expect(";")
    return Clause(word, parser.span(start), role=role, expressions=(value,))


def parse_use(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    name = parser.qualified()
    models: list[str] = []
    if parser.accept("<"):
        models.append(parser.qualified())
        while parser.accept(","):
            models.append(parser.qualified())
        parser.expect(">")
    args = parser.arguments(named_only=True)
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        word,
        parser.span(start),
        name=name,
        expressions=args,
        alias=alias,
        flags=tuple(models),
    )


def parse_alternatives(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    block_mode = "body" if mode == "body" else "constraint"
    if word == "not":
        parser.expect("exists")
    blocks = [
        parser.block("body" if mode == "body" and word == "either" else "constraint")
    ]
    if word == "either":
        parser.expect("or")
        blocks.append(parser.block(block_mode))
        while parser.accept("or"):
            blocks.append(parser.block(block_mode))
    return Clause(word, parser.span(start), blocks=tuple(blocks))


def parse_projection(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    if mode != "query":
        parser.fail(f"{word} only allowed in query")
    if word == "limit":
        count = parser.token("INTEGER").text
        parser.expect(";")
        return Clause(word, parser.span(start), name=count)
    if word == "order":
        parser.expect("by")
    values: list[Expression] = []
    while True:
        expression = parser.expr()
        suffix = ""
        if word == "select" and parser.accept("as"):
            suffix = parser.ident()
        elif word == "order":
            suffix = parser.take().text if parser.peek() in ("asc", "desc") else "asc"
        assert isinstance(expression, Expr)
        values.append(Expr("projection", expression.span, suffix, (expression,)))
        if not parser.accept(","):
            break
    parser.expect(";")
    return Clause(word, parser.span(start), expressions=tuple(values))


def parse_inventory(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    flags: tuple[str, ...] = ()
    role = ""
    if word in ("fields", "parameters") and parser.accept("exact"):
        flags = ("exact",)
    if word == "body":
        if parser.accept("adjacent"):
            flags = ("adjacent",)
        elif parser.accept("linear"):
            flags = ("linear",)
    if word == "fragment":
        role = parser.role()
    block = parser.block("body" if word in ("body", "fragment") else "constraint")
    return Clause(word, parser.span(start), role=role, blocks=(block,), flags=flags)


def parse_exposes(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    role = parser.role()
    parser.expect(";")
    return Clause(word, parser.span(start), role=role)


def parse_interval(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    points: list[Expression] = []
    if word == "restriction":
        parser.expect("between")
        points.append(parser.point())
        parser.expect("and")
        points.append(parser.point())
    else:
        parser.expect("until")
        endpoint = parser.take().text
        if endpoint not in ("next", "exit"):
            parser.fail("gap endpoint must be next or exit")
    return Clause(
        word,
        parser.span(start),
        expressions=tuple(points),
        blocks=(parser.block("effect"),),
        flags=("exit",) if word == "gap" and endpoint == "exit" else (),
    )


def parse_effect(parser: Parser, word: str, start: Span, mode: str) -> Clause:
    expression = parser.expr()
    if expression.kind != "call":
        parser.fail("effect constraint requires an application")
    parser.expect(";")
    return Clause(word, parser.span(start), expressions=(expression,))


ClauseProduction = Callable[["Parser", str, Span, str], Clause]
COMMON_PRODUCTIONS: Mapping[str, ClauseProduction] = MappingProxyType(
    {
        "usages": parse_usages,
        "require": parse_require,
        "edge": parse_edge,
        "walk": parse_edge,
        "tally": parse_tally,
        "at": parse_at_least,
        "from": parse_from,
        "where": parse_condition,
        "bind": parse_condition,
        "use": parse_use,
        "either": parse_alternatives,
        "not": parse_alternatives,
        "optional": parse_alternatives,
        "select": parse_projection,
        "order": parse_projection,
        "limit": parse_projection,
    }
)

CONSTRAINT_PRODUCTIONS: Mapping[str, ClauseProduction] = MappingProxyType(
    {
        "fields": parse_inventory,
        "parameters": parse_inventory,
        "body": parse_inventory,
        "syntax": parse_inventory,
        "fragment": parse_inventory,
        "exposes": parse_exposes,
        "restriction": parse_interval,
        "gap": parse_interval,
    }
)


def parse_clause(parser: Parser, mode: str) -> Clause:
    start = parser.lexer.peek().span
    word = parser.peek()
    # A nested block is a body only inside a body clause; everywhere else it is
    # a constraint block. Derived once because every branch nests the same kind.
    block_mode = "body" if mode == "body" else "constraint"
    # A schema property can have a reserved name, including 'type' or 'body'.
    if parser.lexer.peek().kind == "IDENT":
        mark = parser.mark()
        first = parser.take()
        if parser.accept(":"):
            if mode in ("query", "body"):
                parser.fail("property needs a selector or constraint block")
            value: Expression = parser.matcher()
            parser.expect(";")
            return Clause(
                "property", parser.span(start), name=first.text, expressions=(value,)
            )
        # A schema property may carry a reserved name, so the keyword must be
        # retried as a clause with the identifier unconsumed.
        parser.reset(mark)
    if word == "{":
        blocks = [parser.block(block_mode)]
        parser.expect("or")
        blocks.append(parser.block(block_mode))
        while parser.accept("or"):
            blocks.append(parser.block(block_mode))
        return Clause("either", parser.span(start), blocks=tuple(blocks))
    if word == "when":
        parser.take()
        condition = parser.expr()
        blocks = [parser.block(block_mode)]
        if parser.accept("else"):
            if parser.peek() == "when":
                blocks.append((parser.clause(mode),))
            else:
                blocks.append(parser.block(block_mode))
        return Clause(
            "when", parser.span(start), expressions=(condition,), blocks=tuple(blocks)
        )
    if mode == "effect" and word not in ("forbid", "preserve"):
        parser.fail("effect block accepts properties, forbid and preserve")
    if word == "type_parameter":
        # ``type_parameter $t;`` names a generic parameter a declaration binds.
        # The parameter is a name, not an entity, so the clause stands alone
        # inside the declaration block and the optional block carries nothing.
        if mode == "body":
            parser.fail("type parameters belong to a declaration block")
        parser.take()
        role = parser.role()
        block = parser.block() if parser.peek() == "{" else ()
        parser.expect(";")
        return Clause(
            "selector",
            parser.span(start),
            name="type_parameter",
            role=role,
            blocks=(block,),
        )
    if (
        word in SELECTORS
        and not (word == "macro" and mode == "body")
        or word == "call"
        and mode != "body"
    ):
        # ``call`` is BODY's invocation clause inside a body block, and a call
        # occurrence selector in every other block.
        parser.take()
        role = parser.role()
        block = parser.block()
        alias = parser.alias()
        if alias:
            parser.expect(";")
        return Clause(
            "selector",
            parser.span(start),
            name=word,
            role=role,
            blocks=(block,),
            alias=alias,
        )
    parser.take()
    if word == "initializer" and mode != "body":
        return parse_initializer(parser, word, start, mode)
    production = COMMON_PRODUCTIONS.get(word)
    if production is not None:
        return production(parser, word, start, mode)
    if word == "return" and mode != "body":
        parser.fail("return requires a callable BODY block: callable $owner { body { return $value; } }. Bind $value inside BODY and use --backend indexed.")
    if mode == "query":
        parser.fail(f"{word!r} is not a query clause")
    production = CONSTRAINT_PRODUCTIONS.get(word)
    if production is not None:
        return production(parser, word, start, mode)
    if word in ("forbid", "preserve") and mode == "effect":
        return parse_effect(parser, word, start, mode)
    if mode != "body":
        parser.fail(f"unexpected constraint {word!r}")
    return parser.body_clause(word, start)
