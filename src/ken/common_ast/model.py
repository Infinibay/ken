"""Canonical source AST. IDs are local to one immutable source revision."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal, Any

VERSION = 'common-ast/1'
Knowledge = Literal['known', 'unknown', 'absent', 'unavailable']


@dataclass(frozen=True, slots=True)
class Node:
    id: int
    kind: str
    category: str
    parent: int | None
    ordinal: int
    role: str
    native_role: str
    native_kind: str
    source_id: str
    start: int
    end: int
    line: int
    scope: int
    owner: str
    name: str = ''
    text: str = ''
    operator: str = ''
    type_kind: str = ''
    flags: tuple[str, ...] = ()
    subtree_end: int = 0
    argument_kind: str = ''
    argument_name: str = ''
    argument_position: int | None = None
    source_position: int | None = None


@dataclass(frozen=True, slots=True)
class Scope:
    id: int
    parent: int | None
    node: int
    kind: str
    name: str
    namespace: str
    lookup_parent: int | None
    global_names: tuple[str, ...] = ()
    nonlocal_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Symbol:
    id: int
    name: str
    scope: int
    declaration: int
    kind: str
    source_id: str
    visible_from: int
    initialized_from: int | None
    type_kind: str = 'unknown'
    native_type: str = ''
    mutable: bool | None = None
    flags: tuple[str, ...] = ()
    position: int | None = None
    parameter_kind: str = ''
    native_position: int | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    node: int
    name: str
    scope: int
    mode: str
    symbol: int | None
    status: Knowledge
    reason: str = ''
    availability: str = 'unknown'


@dataclass(frozen=True, slots=True)
class Link:
    source: int
    relation: str
    target: int
    ordinal: int = 0


@dataclass(frozen=True, slots=True)
class Program:
    path: str
    language: str
    nodes: tuple[Node, ...]
    scopes: tuple[Scope, ...]
    symbols: tuple[Symbol, ...]
    references: tuple[Reference, ...]
    links: tuple[Link, ...]
    diagnostics: tuple[str, ...]
    version: str = VERSION

    def validate(self) -> None:
        if self.version != VERSION:
            raise ValueError('incompatible common AST')
        for i,node in enumerate(self.nodes):
            if node.id != i or not 0 <= node.start <= node.end or not i < node.subtree_end <= len(self.nodes):
                raise ValueError('invalid AST node or range')
            if node.parent is not None:
                if not 0 <= node.parent < i or i >= self.nodes[node.parent].subtree_end:
                    raise ValueError('invalid AST parent')
            if not 0 <= node.scope < len(self.scopes):
                raise ValueError('invalid AST scope')
        for i,scope in enumerate(self.scopes):
            if scope.id != i or not 0 <= scope.node < len(self.nodes):
                raise ValueError('invalid scope')
            if any(parent is not None and not 0 <= parent < i for parent in (scope.parent,scope.lookup_parent)):
                raise ValueError('invalid scope ancestry')
        for i,symbol in enumerate(self.symbols):
            if symbol.id != i or not 0 <= symbol.scope < len(self.scopes) or not 0 <= symbol.declaration < len(self.nodes):
                raise ValueError('invalid symbol')
        for ref in self.references:
            if not 0 <= ref.node < len(self.nodes) or not 0 <= ref.scope < len(self.scopes) or ref.symbol is not None and not 0 <= ref.symbol < len(self.symbols):
                raise ValueError('invalid reference')
        for link in self.links:
            if not 0 <= link.source < len(self.nodes) or not 0 <= link.target < len(self.nodes):
                raise ValueError('invalid AST link')

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Program:
        fields = dict(data)
        constructors: dict[str,type[Any]]={'nodes':Node,'scopes':Scope,'symbols':Symbol,'references':Reference,'links':Link}
        for key, constructor in constructors.items():
            fields[key] = tuple(constructor(**{k:tuple(v) if k in ('flags','global_names','nonlocal_names') else v for k,v in row.items()}) for row in data[key])
        fields['diagnostics'] = tuple(data['diagnostics'])
        result=cls(**fields)
        result.validate()
        return result
