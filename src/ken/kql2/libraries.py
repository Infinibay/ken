"""Resolve an explicit immutable library snapshot; never import host code."""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from .syntax import Clause, Declaration, Expr, File, ParseError, SourceExpr
from .syntax.ast import Parameter, TypeName


def resolve(entry: File, libraries: Mapping[str, File]) -> File:
    output: list[Declaration] = []
    seen: set[str] = set()

    def module(tree: File, main: bool = False) -> None:
        if tree.module in seen:
            return
        seen.add(tree.module)
        for dependency in tree.imports:
            if dependency == 'ken.core':
                continue
            imported = entry if dependency == entry.module else libraries.get(dependency)
            if imported is None or imported.module != dependency:
                raise ParseError('missing or mismatched library module: ' + dependency, tree.span)
            module(imported, imported is entry)
        prefix = '' if main else tree.module + '.'
        names = {decl.name:prefix + decl.name for decl in tree.declarations}

        def qualified(name: str) -> str:
            head, dot, tail = name.partition('.')
            return names.get(head, head) + dot + tail

        def type_name(t: TypeName) -> TypeName:
            return replace(t, name=qualified(t.name), arguments=tuple(type_name(a) for a in t.arguments))

        def parameter(p: Parameter) -> Parameter:
            return replace(p, type=type_name(p.type))

        def expression(e: Expr | SourceExpr, local: frozenset[str] = frozenset()) -> Expr | SourceExpr:
            name = qualified(e.value) if e.kind in ('call', 'name') and e.value.partition('.')[0] not in local else e.value
            args = tuple(expression(arg,local) for arg in e.args)
            if isinstance(e, Expr):
                assert all(isinstance(arg, Expr) for arg in args)
                return replace(e, value=name, args=tuple(arg for arg in args if isinstance(arg, Expr)),
                               parameters=tuple(parameter(p) for p in e.parameters))
            return replace(e, value=name, args=args)

        def clause(c: Clause, local: frozenset[str] = frozenset()) -> Clause:
            return replace(c, name=qualified(c.name) if c.kind == 'use' else c.name,
                           flags=tuple(f if f in local else qualified(f) for f in c.flags) if c.kind == 'use' else c.flags,
                           parameters=tuple(parameter(p) for p in c.parameters),
                           expressions=tuple(expression(e,local) for e in c.expressions),
                           blocks=tuple(tuple(clause(child,local) for child in block) for block in c.blocks))

        def declaration(d: Declaration, member: bool = False, local: frozenset[str] = frozenset()) -> Declaration:
            local = local | {name for name,_ in d.generics}
            formula = expression(d.formula,local) if d.formula else None
            assert formula is None or isinstance(formula, Expr)
            return replace(d, name=d.name if member else names[d.name], formula=formula,
                           parameters=tuple(parameter(p) for p in d.parameters),
                           generics=tuple((name,qualified(signature)) for name,signature in d.generics),
                           implements=qualified(d.implements), clauses=tuple(clause(c,local) for c in d.clauses),
                           members=tuple(declaration(m, True, local | {m.name for m in d.members}) for m in d.members))

        output.extend(declaration(d) for d in tree.declarations if main or d.kind != 'query')

    module(entry, True)
    if len({d.name for d in output}) != len(output):
        raise ParseError('library declaration collision', entry.span)
    return replace(entry, declarations=tuple(output), imports=())
