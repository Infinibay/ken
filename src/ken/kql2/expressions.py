"""Finite-domain query expression evaluator, independent of join strategy."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import operator
from typing import Callable, Iterator, Mapping

from .syntax import Expr, Span
from .values import NONE, UNKNOWN, EnumValue, Node, OperationValue, ASTValue, Option, QueryValue, Unknown, conjunction, disjunction, identity, is_unknown, negate


class EvaluationError(ValueError):
    def __init__(self, message: str, span: Span):
        self.span = span
        super().__init__(f'{span.source}:{span.start}: {message}')


@dataclass
class ExpressionContext:
    domain: Callable[[str], tuple[Iterator[QueryValue], bool]]
    property: Callable[[QueryValue, str], QueryValue]
    relation: Callable[[str, tuple[QueryValue, ...]], QueryValue]
    regex: Callable[[str, Expr], bool]
    check: Callable[[], None]
    enums: Mapping[str, EnumValue]
    candidate_domain: Callable[[str, str, Expr, Mapping[str, QueryValue]], tuple[Iterator[QueryValue], bool]] | None = None


def evaluate(expr: Expr, bindings: Mapping[str, QueryValue], context: ExpressionContext) -> QueryValue:
    context.check()
    kind = expr.kind
    if kind == 'type_test':
        from .source_types import matches
        return matches(evaluate(expr.args[0],bindings,context),expr.args[1])
    if kind == 'literal':
        if expr.value == 'undefined':
            return EnumValue('SourceLiteral','undefined')
        return json.loads(expr.value)
    if kind == 'role':
        return bindings[expr.value]
    if kind == 'name':
        return context.enums[expr.value]
    if kind == 'member':
        return context.property(evaluate(expr.args[0],bindings,context),expr.value)
    if kind == 'list':
        return tuple(evaluate(a,bindings,context) for a in expr.args)
    if kind == 'unary':
        value=evaluate(expr.args[0],bindings,context)
        if expr.value=='not':
            return negate(value)
        if is_unknown(value):
            return value
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            return value if expr.value=='+' else -value
        raise EvaluationError('numeric unary operator requires a number',expr.span)
    if kind == 'binary':
        left=evaluate(expr.args[0],bindings,context)
        if expr.value=='and' and left is False:
            return False
        if expr.value=='or' and left is True:
            return True
        if expr.value=='matches':
            return context.regex(left,expr.args[1]) if isinstance(left,str) else UNKNOWN
        right=evaluate(expr.args[1],bindings,context)
        if expr.value=='and':
            return conjunction(left,right)
        if expr.value=='or':
            return disjunction(left,right)
        if expr.value == 'in' and right == ():
            return False
        if is_unknown(left) or is_unknown(right):
            return left if is_unknown(left) else right
        if expr.value in ('==','!='):
            equal=identity(left)==identity(right)
            return equal if expr.value=='==' else not equal
        if expr.value=='in':
            assert isinstance(right,tuple)
            return any(identity(left)==identity(v) for v in right)
        operations={'<':operator.lt,'>':operator.gt,'<=':operator.le,'>=':operator.ge,
                    '+':operator.add,'-':operator.sub,'*':operator.mul,'/':operator.truediv,'%':operator.mod}
        try:
            # Type checking admits matching strings for comparisons and numeric
            # values for arithmetic. operator.* does not execute source methods.
            result=operations[expr.value](left,right)  # type: ignore[operator]
        except (ZeroDivisionError,OverflowError,TypeError) as exc:
            raise EvaluationError(str(exc),expr.span) from exc
        if isinstance(result,float) and not math.isfinite(result):
            raise EvaluationError('nonfinite calculation result',expr.span)
        return result
    if kind == 'call':
        arguments=tuple(evaluate(a.args[0],bindings,context) for a in expr.args)
        if expr.value=='in_directory':
            node,directory=arguments
            return directory in node.path.split('/')[:-1] if isinstance(node,(Node,OperationValue,ASTValue)) and isinstance(directory,str) else UNKNOWN
        if expr.value=='stable_id':
            return arguments[0].local_id if isinstance(arguments[0],(Node,OperationValue,ASTValue)) else UNKNOWN
        return context.relation(expr.value,arguments)
    if kind in ('aggregate','quantifier'):
        domains=[]
        complete=True
        for parameter in expr.parameters:
            domain_values,closed=(context.candidate_domain(parameter.type.name, parameter.role, expr.args[0], bindings)
                                  if context.candidate_domain else context.domain(parameter.type.name))
            domains.append((parameter.role,tuple(domain_values)))
            complete &= closed
        def tuples(index: int, local: dict[str,QueryValue]) -> Iterator[dict[str,QueryValue]]:
            context.check()
            if index==len(domains):
                yield local
                return
            role,values=domains[index]
            for value in values:
                yield from tuples(index+1,{**local,role:value})
        uncertain=not complete
        projected: dict[object,QueryValue]={}
        contributions: list[QueryValue]=[]
        for local in tuples(0,dict(bindings)):
            predicate=evaluate(expr.args[0],local,context)
            if predicate is False:
                continue
            if is_unknown(predicate):
                uncertain=True
                continue
            if expr.value=='exists':
                return True
            if expr.value=='forall':
                condition=evaluate(expr.args[1],local,context)
                if condition is False:
                    return False
                uncertain |= is_unknown(condition)
                continue
            value=evaluate(expr.args[1],local,context)
            if is_unknown(value):
                uncertain=True
            else:
                projected[identity(value)]=value
                contributions.append(value)
        if expr.value=='exists':
            return Unknown('open_world') if uncertain else False
        if expr.value=='forall':
            return Unknown('open_world') if uncertain else True
        if uncertain:
            return Unknown('incomplete_aggregate_domain')
        values=list(projected.values())
        if expr.value=='count':
            return len(values)
        if expr.value in ('sum','sum_by'):
            return _sum(contributions if expr.value=='sum_by' else values,expr.span)
        if not values:
            return NONE
        if expr.value=='avg':
            return Option(True,_sum(values,expr.span)/len(values))
        ordered=sorted(values)  # type: ignore[type-var]
        return Option(True,ordered[0] if expr.value=='min' else ordered[-1])
    raise EvaluationError(f'unknown expression operation {kind}',expr.span)


def _sum(values: list[QueryValue], span: Span) -> int | float:
    total: int | float = 0
    for value in values:
        if not isinstance(value,(int,float)) or isinstance(value,bool):
            raise EvaluationError('sum requires numbers',span)
        total += value
    if isinstance(total,float) and not math.isfinite(total):
        raise EvaluationError('nonfinite aggregate',span)
    return total
