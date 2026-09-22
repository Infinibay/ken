"""Static signature checking and hygienic model specialization."""
from __future__ import annotations

from dataclasses import replace

from .syntax import Clause, Declaration, Expr, File, ParseError, SourceExpr


def specialize(tree: File) -> File:
    declarations = {d.name:d for d in tree.declarations}
    if len(declarations) != len(tree.declarations):
        raise ParseError('duplicate declaration', tree.span)
    models = {d.name:d for d in tree.declarations if d.kind == 'model'}
    output: list[Declaration] = []
    instances: dict[tuple[str, tuple[str, ...]], str] = {}

    def rename(name: str, mapping: dict[str, str]) -> str:
        head, dot, rest = name.partition('.')
        return mapping.get(head, head) + dot + rest

    def expr(value: Expr | SourceExpr, mapping: dict[str, str]) -> Expr | SourceExpr:
        name = rename(value.value, mapping) if value.kind in ('call','name') else value.value
        args = tuple(expr(arg, mapping) for arg in value.args)
        if isinstance(value, Expr):
            assert all(isinstance(arg, Expr) for arg in args)
            return replace(value, value=name, args=tuple(arg for arg in args if isinstance(arg, Expr)))
        return replace(value, value=name, args=args)

    for model in models.values():
        signature = declarations.get(model.implements)
        if signature is None or signature.kind != 'signature':
            raise ParseError('model implements an unknown signature', model.span)
        members = {p.name:p for p in model.members}
        if len(members) != len(model.members) or len({p.name for p in signature.members}) != len(signature.members):
            raise ParseError('duplicate model/signature predicate', model.span)
        for expected in signature.members:
            actual = members.get(expected.name)
            if actual is None or tuple(p.type for p in expected.parameters) != tuple(p.type for p in actual.parameters):
                raise ParseError('model predicate signature mismatch: ' + expected.name, model.span)
        local = {name:model.name + '.' + name for name in members}
        for member in model.members:
            assert member.formula is not None
            formula = expr(member.formula, local)
            assert isinstance(formula, Expr)
            output.append(replace(member, name=local[member.name], formula=formula))

    def clauses(items: tuple[Clause, ...], mapping: dict[str,str]) -> tuple[Clause, ...]:
        result = []
        for item in items:
            item = replace(item, expressions=tuple(expr(e, mapping) for e in item.expressions),
                           blocks=tuple(clauses(block, mapping) for block in item.blocks))
            if item.kind == 'use':
                arguments = tuple(rename(name, mapping) for name in item.flags)
                target = declarations.get(item.name)
                if target is not None and target.kind == 'pattern' and target.generics:
                    if len(arguments) != len(target.generics):
                        raise ParseError('wrong number of model arguments', item.span)
                    substitutions = {}
                    for (parameter, signature_name), argument in zip(target.generics, arguments):
                        model = models.get(argument)
                        if model is None or model.implements != signature_name:
                            raise ParseError('model argument does not implement ' + signature_name, item.span)
                        substitutions[parameter] = argument
                    key = (target.name, arguments)
                    if key not in instances:
                        if len(instances) >= 128:
                            raise ParseError('model specialization limit', item.span)
                        instances[key] = f'@model:{len(instances)}:{target.name}'
                        body = clauses(target.clauses, substitutions)
                        output.append(replace(target, name=instances[key], generics=(), clauses=body))
                    item = replace(item, name=instances[key], flags=())
                elif arguments:
                    raise ParseError('model arguments require a generic pattern', item.span)
            result.append(item)
        return tuple(result)

    for declaration in tree.declarations:
        if declaration.kind in ('signature','model') or declaration.generics:
            continue
        output.append(replace(declaration, clauses=clauses(declaration.clauses, {})))
    if len({d.name for d in output}) != len(output):
        raise ParseError('model predicate name collides with declaration', tree.span)
    return replace(tree, declarations=tuple(output))
