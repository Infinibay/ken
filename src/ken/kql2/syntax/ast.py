"""Immutable syntax nodes; byte spans always refer to the original UTF-8 input."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class Span:
    source: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TypeName:
    name: str
    arguments: tuple[TypeName, ...] = ()


@dataclass(frozen=True, slots=True)
class Parameter:
    type: TypeName
    role: str
    direction: str = "relation"


@dataclass(frozen=True, slots=True)
class Expr:
    """A query calculation or formula, never an executable host expression."""
    kind: str
    span: Span
    value: str = ""
    args: tuple[Expr, ...] = ()
    parameters: tuple[Parameter, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceExpr:
    """A pattern for an expression in the source program."""
    kind: str
    span: Span
    value: str = ""
    args: tuple[SourceExpr | Expr, ...] = ()


Expression: TypeAlias = Expr | SourceExpr


@dataclass(frozen=True, slots=True)
class Clause:
    kind: str
    span: Span
    name: str = ""
    role: str = ""
    expressions: tuple[Expression, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    blocks: tuple[tuple[Clause, ...], ...] = ()
    alias: str = ""
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Declaration:
    kind: str
    name: str
    span: Span
    parameters: tuple[Parameter, ...] = ()
    generics: tuple[tuple[str, str], ...] = ()
    clauses: tuple[Clause, ...] = ()
    formula: Expr | None = None
    members: tuple[Declaration, ...] = ()
    values: tuple[str, ...] = ()
    implements: str = ""


@dataclass(frozen=True, slots=True)
class File:
    language: str
    module: str
    imports: tuple[str, ...]
    declarations: tuple[Declaration, ...]
    span: Span
