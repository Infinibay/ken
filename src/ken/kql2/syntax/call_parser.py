"""Call and construction productions shared by BODY and declaration initializers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import Clause, Expression, SourceExpr

if TYPE_CHECKING:
    from .parser import Parser


def call(parser: Parser) -> Clause:
    start = parser.expect("call").span
    flags: tuple[str, ...] = ()
    if parser.accept("on"):
        # ``call on $item { ... }`` invokes *something on* that place without naming
        # the operation: the receiver is the evidence, which is what a collection of
        # callbacks supplies.
        flags = ("on",)
    elif parser.accept("qualify"):
        # ``call qualify $parameter { ... }`` invokes an operation that the *type
        # parameter* itparser selects (C++ ``P::operation``): there is no stored object,
        # the qualifier is the declaration's generic parameter.
        flags = ("qualify",)
    elif parser.accept("alongside"):
        # ``call alongside $x { ... }`` states that this occurrence is the *sibling*
        # operand of the call just matched, inside one statement. Operand order is
        # otherwise not guessed, so the spelling is the claim that the two
        # occurrences are peers (``left.evaluate() + right.evaluate()``).
        flags = ("alongside",)
    role = parser.role()
    # ``call $table[$key] { ... }``: the callee is the element that key selects out
    # of the bound container — element origin in callee position, the same spelling
    # ``argument $table[$key]`` already uses for an argument.
    expressions: tuple[Expression, ...] = ()
    if parser.accept("["):
        container = SourceExpr("role", start, role, ())
        key = parser.expr(True)
        parser.expect("]")
        expressions = (SourceExpr("index", parser.span(start), "", (container, key)),)
    parser.expect("{")
    constraints: list[Clause] = []
    while parser.peek() != "}":
        if parser.peek() == "argument":
            constraints.append(parser.argument())
        elif parser.peek() == "argument_pack":
            arg_start = parser.take().span
            pack = parser.role()
            constraints.append(
                Clause(
                    "argument_pack",
                    parser.span(arg_start),
                    role=pack,
                    blocks=(parser.block(),),
                )
            )
        else:
            constraint = parser.clause("constraint")
            if constraint.kind not in ("property", "where"):
                parser.fail("invalid call constraint")
            constraints.append(constraint)
    parser.expect("}")
    return Clause(
        "call",
        parser.span(start),
        role=role,
        expressions=expressions,
        blocks=(tuple(constraints),),
        flags=flags,
    )


def argument(parser: Parser) -> Clause:
    """``argument <operand> [for $param | at N | at any | at name("x")];``.

    Shared by ``call`` and ``construct``. A call states the values it is
    entered with; so does a construction (``new Idle(this)``), where the
    argument is the value the constructor symbol was invoked with.
    """
    arg_start = parser.take().span
    value = None if parser.peek() == "from" else parser.expr(True)
    derived = (
        SourceExpr("from", parser.span(arg_start), parser.role(), ())
        if parser.accept("from")
        else None
    )
    parameter = parser.role() if parser.accept("for") else ""
    if not parameter:
        parser.expect("at")
    if parameter:
        position = ""
    elif parser.accept("name"):
        parser.expect("(")
        position = parser.token("STRING").text
        parser.expect(")")
    elif parser.accept("any"):
        position = "any"
    else:
        position = parser.token("INTEGER").text
    alias = parser.alias()
    parser.expect(";")
    return Clause(
        "argument",
        parser.span(arg_start),
        name=position,
        role=parameter,
        expressions=tuple(e for e in (value, derived) if e is not None),
        alias=alias,
    )


def construct(parser: Parser) -> Clause:
    """``construct $type { initializer $place; }``: a source construction.

    Not every language constructs through a callable symbol: Go and Rust use
    keyed literals and struct expressions. The construction is accredited by the
    type it produces and by the place whose value it carries.

    ``initializer $field from $value;`` names the value the construction stores
    in that place. A keyed literal initializes a field with a value that never
    passes through a parameter, so the field and the value it carries are both
    evidence; without ``from`` the place is itparser what the construction stores.
    """
    start = parser.expect("construct").span
    role = parser.role()
    parser.expect("{")
    constraints: list[Clause] = []
    while parser.peek() != "}":
        if parser.peek() == "argument":
            constraints.append(parser.argument())
            continue
        if parser.peek() == "initializer":
            item_start = parser.take().span
            place = parser.role()
            values: tuple[Expression, ...] = ()
            if parser.accept("from"):
                values = (parser.expr(True),)
            properties = parser.block() if parser.peek() == "{" else ()
            parser.expect(";")
            constraints.append(
                Clause(
                    "initializer",
                    parser.span(item_start),
                    role=place,
                    expressions=values,
                    blocks=(properties,),
                )
            )
            continue
        constraint = parser.clause("constraint")
        if constraint.kind not in ("property", "where", "argument"):
            parser.fail("invalid construct constraint")
        constraints.append(constraint)
    parser.expect("}")
    return Clause(
        "construct", parser.span(start), role=role, blocks=(tuple(constraints),)
    )
