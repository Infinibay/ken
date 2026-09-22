"""Source statement productions, dispatched by leading token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import Clause, Expression, Span

if TYPE_CHECKING:
    from .parser import Parser

from collections.abc import Callable, Mapping
from types import MappingProxyType


def parse_macro(parser: Parser, word: str, start: Span) -> Clause:
    role = parser.role()
    parser.expect(";")
    return Clause("macro", parser.span(start), role=role)


def parse_initializer(parser: Parser, word: str, start: Span) -> Clause:
    return Clause(word, parser.span(start), blocks=(parser.block("body"),))


def parse_adjacent(parser: Parser, word: str, start: Span) -> Clause:
    parser.expect(";")
    return Clause(word, parser.span(start))


def parse_let(parser: Parser, word: str, start: Span) -> Clause:
    role = parser.role()
    parser.expect("=")
    values: tuple[Expression, ...]
    let_blocks: tuple[tuple[Clause, ...], ...]
    if parser.peek() == "construct":
        values, let_blocks = (), ((parser.construct(),),)
    elif parser.peek() == "call":
        values, let_blocks = (), ((parser.call(),),)
    else:
        values, let_blocks = (parser.expr(True),), ()
    # ``let $value = $items[$index] writes: 2;`` — an indexed read whose place is
    # written again later (the intern rewrite) still names the element it read,
    # provided the pattern says how many writes that place carries.
    expected_writes = ""
    if parser.accept("writes"):
        parser.expect(":")
        expected_writes = parser.take().text
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        word,
        parser.span(start),
        name=expected_writes,
        role=role,
        expressions=values,
        blocks=let_blocks,
        alias=alias,
    )


def parse_clear(parser: Parser, word: str, start: Span) -> Clause:
    # ``clear $collection after $iteration as $reset;`` — the reset that closes a
    # drain: a statement empties the collection once the walk over it is over.
    collection = parser.role()
    loop = parser.role() if parser.accept("after") else ""
    alias = parser.alias()
    parser.expect(";")
    return Clause(word, parser.span(start), role=collection, name=loop, alias=alias)


def parse_call(parser: Parser, word: str, start: Span) -> Clause:
    mark = parser._char_offset(start.start)
    parser.reset(mark)
    call = parser.call()
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        "call",
        parser.span(start),
        role=call.role,
        expressions=call.expressions,
        blocks=call.blocks,
        alias=alias,
        flags=call.flags,
    )


def parse_assign(parser: Parser, word: str, start: Span) -> Clause:
    mark = parser._char_offset(start.start)
    parser.reset(mark)
    place = parser.expr(True, 100)
    if place.kind not in ("role", "member", "index"):
        parser.fail("assignment requires a place")
    operator = parser.take().text
    if operator not in ("=", "+=", "-=", "*=", "/=", "%="):
        parser.fail("expected assignment operator")
    value = parser.expr(True)
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        "assign",
        parser.span(start),
        name=operator,
        expressions=(place, value),
        alias=alias,
    )


def parse_jump(parser: Parser, word: str, start: Span) -> Clause:
    if word == "break" and parser.peek().startswith("$"):
        target = parser.role()
        alias = parser.alias()
        parser.expect(";")
        return Clause("break", parser.span(start), role=target, alias=alias)

    flags: tuple[str, ...] = (
        ("from",) if word == "yield" and parser.accept("from") else ()
    )
    values = (
        ()
        if word in ("break", "continue")
        or word == "return"
        and parser.peek() in (";", "as", "from")
        else (parser.expr(True),)
    )
    alias = parser.alias() if word not in ("break", "continue") else ""
    # ``return $replica copies $state;`` — the returned object carries a
    # field copied from the receiver's field of that name.
    blocks: tuple[tuple[Clause, ...], ...] = ()
    if word == "return" and parser.accept("from"):
        # ``return $converted from $forward;`` -- the returned value is a computation
        # that consumes the place (the delegated call's result), not the place itparser.
        blocks = ((Clause("from", parser.span(start), role=parser.role()),),)
    elif word == "return" and parser.peek() == "copies":
        parser.take()
        field = parser.role()
        blocks = ((Clause("copies", parser.span(start), role=field),),)
    parser.expect(";")
    return Clause(
        word,
        parser.span(start),
        expressions=values,
        alias=alias,
        flags=flags,
        blocks=blocks,
    )


def parse_conditional(parser: Parser, word: str, start: Span) -> Clause:
    parser.expect("(")
    condition = parser.expr(True)
    parser.expect(")")
    alias = parser.alias()
    blocks = [parser.block("body")]
    if word == "if" and parser.accept("else"):
        if parser.peek() == "if":
            next_start = parser.take().span
            blocks.append((parser.body_clause("if", next_start),))
        else:
            blocks.append(parser.block("body"))
    return Clause(
        word,
        parser.span(start),
        expressions=(condition,),
        blocks=tuple(blocks),
        alias=alias,
    )


def parse_insert(parser: Parser, word: str, start: Span) -> Clause:
    # ``insert $listener into $listeners;`` / ``insert $handler into $map at $key;``
    # An insertion is a collection effect: it names the value, the collection and
    # (optionally) the key it lands under.
    value = parser.expr(True)
    parser.expect("into")
    # The destination is a place: ``$listeners``, ``$map[$topic]``.
    place = parser.expr(True, 100)
    expressions_list: list[Expression] = [value]
    if place.kind == "index":
        collection, key = place.args[0], place.args[1]
        expressions_list.append(key)
    elif place.kind == "role":
        collection = place
        if parser.accept("at"):
            expressions_list.append(parser.expr(True))
    else:
        parser.fail("insert destination must be a place")
    # ``insert $handler into $table at $key writes: 1;`` states how many indexed
    # writes to that collection its owner performs, the count the write inventory
    # publishes, exactly as ``let $read = $pool[$key] writes: 2`` does for a read.
    expected_writes = ""
    if parser.accept("writes"):
        parser.expect(":")
        expected_writes = parser.take().text
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        "insert",
        parser.span(start),
        role=collection.value,
        name=expected_writes,
        expressions=tuple(expressions_list),
        alias=alias,
    )


def parse_for(parser: Parser, word: str, start: Span) -> Clause:
    if parser.accept("{"):
        parser.expect("init")
        init = parser.block("body")
        parser.expect("condition")
        condition = parser.expr(True)
        parser.expect(";")
        parser.expect("step")
        step = parser.block("body")
        parser.expect("body")
        body = parser.block("body")
        parser.expect("}")
        return Clause(
            "for_c",
            parser.span(start),
            expressions=(condition,),
            blocks=(init, step, body),
        )
    role = parser.role()
    parser.expect("in")
    iterable = parser.expr(True)
    return Clause(
        word,
        parser.span(start),
        role=role,
        expressions=(iterable,),
        blocks=(parser.block("body"),),
    )


def parse_try(parser: Parser, word: str, start: Span) -> Clause:
    blocks = [parser.block("body")]
    catches: list[Clause] = []
    while parser.accept("catch"):
        catch_start = parser.last
        role = parser.role()
        conditions: tuple[Expression, ...] = ()
        if parser.accept("when"):
            parser.expect("(")
            conditions = (parser.expr(True),)
            parser.expect(")")
        catch_body = parser.block("body")
        catches.append(
            Clause(
                "catch",
                parser.span(catch_start),
                role=role,
                expressions=conditions,
                blocks=(catch_body,),
            )
        )
    blocks.append(tuple(catches))
    otherwise = parser.block("body") if parser.accept("else") else None
    final = parser.block("body") if parser.accept("finally") else None
    if not catches and (final is None or otherwise is not None):
        parser.fail("try requires catch or finally; else requires catch")
    blocks += [otherwise or (), final or ()]
    flags = tuple(
        n for n, b in (("else", otherwise), ("finally", final)) if b is not None
    )
    return Clause(word, parser.span(start), blocks=tuple(blocks), flags=flags)


def parse_iterate(parser: Parser, word: str, start: Span) -> Clause:
    flags: tuple[str, ...] = ()
    if parser.accept("keys"):
        # ``iterate keys of $registry as $key`` walks what the map is keyed by.
        parser.expect("of")
        flags = ("keys",)
    elif parser.accept("copy"):
        # ``iterate copy of $listeners as $item`` walks the snapshot the source
        # took before the walk, so a registration during it cannot extend it.
        parser.expect("of")
        flags = ("copy",)
    source = parser.expr(True)
    parser.expect("as")
    role = parser.role()
    output = parser.role() if parser.accept("into") else ""
    alias = parser.alias()
    block = parser.block()
    if any(c.kind not in ("property", "body", "where", "restriction") for c in block):
        parser.fail("invalid iteration constraint")
    return Clause(
        word,
        parser.span(start),
        name=output,
        role=role,
        expressions=(source,),
        blocks=(block,),
        alias=alias,
        flags=flags,
    )


def parse_task(parser: Parser, word: str, start: Span) -> Clause:
    role = parser.role()
    alias = ""
    if word == "spawn":
        parser.expect("as")
        alias = parser.role()
    parser.expect(";")
    return Clause(word, parser.span(start), role=role, alias=alias)


def parse_channel(parser: Parser, word: str, start: Span) -> Clause:
    values: tuple[Expression, ...] = (parser.expr(True),)
    alias = ""
    if word == "send":
        parser.expect("to")
        values += (parser.expr(True),)
    else:
        parser.expect("as")
        alias = parser.role()
    parser.expect(";")
    return Clause(word, parser.span(start), expressions=values, alias=alias)


BodyProduction = Callable[["Parser", str, Span], Clause]
BODY_PRODUCTIONS: Mapping[str, BodyProduction] = MappingProxyType(
    {
        "macro": parse_macro,
        "initializer": parse_initializer,
        "adjacent": parse_adjacent,
        "let": parse_let,
        "clear": parse_clear,
        "call": parse_call,
        "return": parse_jump,
        "throw": parse_jump,
        "yield": parse_jump,
        "await": parse_jump,
        "break": parse_jump,
        "continue": parse_jump,
        "if": parse_conditional,
        "while": parse_conditional,
        "insert": parse_insert,
        "for": parse_for,
        "try": parse_try,
        "iterate": parse_iterate,
        "spawn": parse_task,
        "join": parse_task,
        "acquire": parse_task,
        "release": parse_task,
        "send": parse_channel,
        "receive": parse_channel,
    }
)


def parse_body_clause(parser: Parser, word: str, start: Span) -> Clause:
    """The leading token has already been consumed by clause dispatch."""
    production = BODY_PRODUCTIONS.get(word)
    if production is not None:
        return production(parser, word, start)
    if word.startswith("$"):
        return parse_assign(parser, word, start)
    parser.fail(f"unknown BODY instruction {word!r}")
