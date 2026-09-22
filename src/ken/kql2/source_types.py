"""Typed annotation descriptors; absent evidence is not the source type unknown."""
from __future__ import annotations

from ken.structural.type_refs import TypeRef
from .syntax import Expr, SourceExpr, ParseError
from .values import QueryValue, Unknown, conjunction, disjunction, is_unknown

ALIASES = {'integer':'int','string':'str','boolean':'bool','floating':'float',
           'int':'int','str':'str','bool':'bool','float':'float','char':'char','number':'number',
           'any':'any','unknown':'unknown','never':'never','void':'void','null':'null',
           'array':'array','slice':'slice','list':'list','map':'map','set':'set','tuple':'tuple',
           'optional':'optional','union':'union','reference':'reference','pointer':'pointer'}


def validate_matcher(expr: Expr | SourceExpr) -> None:
    if expr.kind == 'wildcard':
        return
    if expr.kind == 'call' and expr.value == 'oneof' and expr.args:
        for arg in expr.args:
            if arg.value:
                raise ParseError('oneof expects positional type matchers',arg.span)
            validate_matcher(arg.args[0])
        return
    if (expr.kind not in ('name','source_type') and not (expr.kind == 'literal' and expr.value == 'null')) or expr.value not in ALIASES:
        raise ParseError('unknown source type matcher',expr.span)
    arity = {'array':1,'slice':1,'list':1,'map':2,'set':1,'optional':1,'reference':1,'pointer':1}
    if expr.args and expr.value in arity and len(expr.args) != arity[expr.value]:
        raise ParseError('source type matcher arity mismatch',expr.span)
    if expr.args and expr.value not in arity and expr.value not in ('tuple','union'):
        raise ParseError('primitive type does not take type arguments',expr.span)
    for arg in expr.args:
        validate_matcher(arg)


def matches(actual: QueryValue, expected: Expr) -> QueryValue:
    if expected.kind == 'wildcard':
        return True
    if is_unknown(actual):
        return actual
    if not isinstance(actual,TypeRef):
        return Unknown('type_descriptor_unavailable')
    if expected.kind == 'call' and expected.value == 'oneof':
        result: QueryValue = False
        for arg in expected.args:
            result = disjunction(result,matches(actual,arg.args[0]))
        return result
    if actual.kind in ('opaque','generic'):
        return Unknown('unresolved_type_family')
    if actual.kind != ALIASES[expected.value]:
        return False
    if not expected.args:
        return True
    if not actual.arguments:
        return Unknown('type_arguments_unavailable')
    if len(actual.arguments) != len(expected.args):
        return False
    result = True
    for a,b in zip(actual.arguments,expected.args):
        result = conjunction(result,matches(a,b))
    return result
