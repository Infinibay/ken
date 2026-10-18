"""Generic expression-pattern forms shared by validation and BODY matching."""
import json
from collections.abc import Mapping, Sequence
from ken.structural.model import Operation
from .syntax import Expr, SourceExpr, ParseError


def literal_boolean(op: Operation, children: Mapping[str, Sequence[Operation]]) -> bool | None:
    """Boolean literals keep their value through grammar parentheses."""
    seen: set[str] = set()
    while op.native_kind in {'parenthesized_expression', 'condition_clause'} and op.id not in seen:
        seen.add(op.id)
        operands = [child for child in children.get(op.id, ()) if 'comment' not in child.native_kind]
        if len(operands) != 1:
            return None
        op = operands[0]
    text = op.attrs.get('text')
    return {'True': True, 'true': True, 'False': False, 'false': False}.get(text) if isinstance(text, str) else None


def binary_parts(expression: Expr | SourceExpr):
    """A binary source expression with an explicit operand/operator matcher."""
    arguments = {argument.value: argument.args[0] for argument in expression.args}
    if (len(arguments) != len(expression.args)
            or set(arguments) != {'left','operator','right'}):
        raise ParseError('binary requires left:, operator:, and right: exactly once',expression.span)
    operator = arguments['operator']
    choices = operator.args if operator.kind == 'list' else (operator,)
    def is_string(choice):
        try:
            return choice.kind == 'literal' and isinstance(json.loads(choice.value),str)
        except ValueError:
            return False
    if operator.kind != 'wildcard' and (not choices or any(not is_string(choice) for choice in choices)):
        raise ParseError('binary operator requires _, a string, or a nonempty list of strings',operator.span)
    return arguments['left'], operator, arguments['right']


def matches_operator(operator: Expr | SourceExpr, actual: str) -> bool:
    if operator.kind == 'wildcard':
        return True
    choices = operator.args if operator.kind == 'list' else (operator,)
    return actual in {json.loads(choice.value) for choice in choices}
