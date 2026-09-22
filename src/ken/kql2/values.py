"""Typed query values and Kleene knowledge shared by execution operators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ken.structural_store import Node
from ken.structural.type_refs import TypeRef
from ken.common_ast.model import Node as CommonNode


@dataclass(frozen=True, slots=True)
class Unknown:
    reason: str = 'capability_missing'


@dataclass(frozen=True, slots=True)
class Option:
    present: bool
    value: QueryValue = None


@dataclass(frozen=True, slots=True)
class EnumValue:
    type: str
    name: str


@dataclass(frozen=True, slots=True)
class OperationValue:
    snapshot: int
    local_id: str
    kind: str
    native_kind: str
    path: str
    line: int
    owner: str
    language: str
    execution: str = 'unknown'


@dataclass(frozen=True, slots=True)
class ASTValue:
    snapshot: int
    unit: int
    node: CommonNode
    path: str
    language: str
    namespace: str
    scope_kind: str

    @property
    def local_id(self) -> str:
        return self.path+'::ast:'+str(self.node.id)

    def __getattr__(self, name: str):
        if name=='normalized': return self.node.category!='opaque'
        return getattr(self.node,{'start_byte':'start','end_byte':'end'}.get(name,name))


QueryValue: TypeAlias = str | int | float | bool | None | Node | TypeRef | OperationValue | ASTValue | Unknown | Option | EnumValue | tuple['QueryValue', ...]
UNKNOWN = Unknown()
NONE = Option(False)


def is_unknown(value: object) -> bool:
    return isinstance(value, Unknown)


def identity(value: QueryValue) -> object:
    """Set semantics must not unify True, 1 and 1.0 through Python equality."""
    if isinstance(value, tuple):
        return ('Tuple',tuple(identity(v) for v in value))
    if isinstance(value, Option):
        return ('Option',value.present,identity(value.value))
    return (type(value).__name__,value)


def negate(value: QueryValue) -> QueryValue:
    return value if is_unknown(value) else not value


def conjunction(left: QueryValue, right: QueryValue) -> QueryValue:
    if left is False or right is False:
        return False
    if is_unknown(left):
        return left
    if is_unknown(right):
        return right
    return True


def disjunction(left: QueryValue, right: QueryValue) -> QueryValue:
    if left is True or right is True:
        return True
    if is_unknown(left):
        return left
    if is_unknown(right):
        return right
    return False
