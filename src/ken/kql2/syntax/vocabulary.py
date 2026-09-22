"""Lexical vocabulary and Pratt binding powers for the two expression dialects."""

SELECTORS = frozenset(
    "module_decl type class interface trait field property callable method function constructor param receiver var value operation macro iteration task lock region import_decl export_decl node expression statement constant".split()
)
RESERVED = SELECTORS | frozenset(
    "language module import pattern predicate query enum signature model implements in out from where bind use as exposes either or not exists optional fields parameters exact select order by asc desc limit body adjacent linear syntax let call argument at any name argument_pack fragment restriction between and gap until next exit initializer forbid preserve if else while for init condition step try catch when finally return throw yield await break continue iterate into spawn join acquire release send to receive true false null undefined forall count sum sum_by min max avg new matches".split()
)
QUERY_BP = {
    "or": 10,
    "and": 20,
    "==": 30,
    "!=": 30,
    "<": 30,
    "<=": 30,
    ">": 30,
    ">=": 30,
    "in": 30,
    "matches": 30,
    "+": 60,
    "-": 60,
    "*": 70,
    "/": 70,
    "%": 70,
}
RESERVED |= frozenset(("edge", "walk", "tally", "distinct", "require", "every", "of"))
SOURCE_BP = {**QUERY_BP, "|": 35, "^": 40, "&": 45, "<<": 50, ">>": 50, "**": 90}
SOURCE_BP.pop("matches")
