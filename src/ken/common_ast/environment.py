"""Visibility by lexical scope; initialization is a separate, conservative fact."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable
from .model import Scope, Symbol, Knowledge


@dataclass(frozen=True, slots=True)
class Resolution:
    symbol: int | None
    status: Knowledge
    availability: str
    reason: str


class Environment:
    def __init__(self, scopes: Iterable[Scope], symbols: Iterable[Symbol], *, language: str):
        self.scopes=tuple(scopes)
        self.symbols=tuple(symbols)
        self.language=language
        self.names: dict[tuple[int,str],list[Symbol]]=defaultdict(list)
        for symbol in self.symbols:
            self.names[symbol.scope,symbol.name].append(symbol)
        for items in self.names.values():
            items.sort(key=lambda s:(s.visible_from,s.declaration),reverse=True)

    def execution_scope(self, scope: int) -> int:
        while self.scopes[scope].parent is not None and self.scopes[scope].kind not in ('module','callable','comprehension','deferred_block'):
            scope=self.scopes[scope].parent  # type: ignore[assignment]
        return scope

    def resolve(self, name: str, scope: int, point: int) -> Resolution:
        if not 0<=scope<len(self.scopes) or point<0:
            raise ValueError('invalid lookup context')
        origin=scope
        nonlocal_only=False
        directive_scope=scope
        while self.scopes[directive_scope].kind not in ('module','callable','type','comprehension'):
            parent=self.scopes[directive_scope].parent
            if parent is None: break
            directive_scope=parent
        directive=self.scopes[directive_scope]
        if name in directive.global_names:
            scope=0
        elif name in directive.nonlocal_names:
            parent=directive.lookup_parent
            if parent is None:
                return Resolution(None,'unknown','unknown','nonlocal_target_missing')
            scope=parent
            nonlocal_only=True
        while True:
            if nonlocal_only and self.scopes[scope].kind=='module':
                return Resolution(None,'unknown','unknown','nonlocal_target_missing')
            candidates=[s for s in self.names.get((scope,name),()) if s.visible_from<=point]
            if candidates:
                if len(candidates)>1 and any(s.kind in ('callable','type') for s in candidates):
                    return Resolution(None,'unknown','unknown','overload_or_redefinition')
                symbol=candidates[0]
                availability='unknown'
                reason='lexical_binding'
                if any(flag in symbol.flags for flag in ('conditional_init','dynamic_scope','uncertain_lifetime')):
                    reason='path_sensitive_initialization_required'
                elif self.execution_scope(origin)!=self.execution_scope(symbol.scope):
                    reason='cross_execution_context'
                elif symbol.initialized_from is not None:
                    availability='available' if point>=symbol.initialized_from else 'unavailable'
                    reason='source_initialization' if availability=='available' else 'before_initialization'
                return Resolution(symbol.id,'known',availability,reason)
            parent=self.scopes[scope].lookup_parent
            if parent is None:
                return Resolution(None,'unknown','unknown','unresolved_name')
            scope=parent
