"""Small exact rational calculator. No eval, calls, names, or I/O."""
from __future__ import annotations

import ast
import re
from fractions import Fraction
from typing import Any


def calculate(expression: str) -> dict[str, Any]:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 400:
        raise ValueError('Arithmetic expression: 1..400 characters')
    try:
        tree = ast.parse(expression, mode='eval')
    except (SyntaxError, RecursionError) as exc:
        raise ValueError('Invalid arithmetic expression') from exc
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('Expression too complex')

    def evaluate(node: ast.AST) -> Fraction:
        value: Fraction
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            token = ast.get_source_segment(expression, node)
            if token is None or len(token) > 30:
                raise ValueError('Number too long')
            exponent = re.search(r'[eE]([+-]?\d+)$', token)
            if exponent and abs(int(exponent[1])) > 100:
                raise ValueError('Decimal exponent magnitude limit')
            value = Fraction(token)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            elif isinstance(node.op, ast.Div): value = left / right
            else:
                if right.denominator != 1 or abs(right) > 16:
                    raise ValueError('Exponent must be an integer between -16 and 16')
                value = left ** int(right)
        else:
            raise ValueError('Only numbers, parentheses and + - * / ** are supported')
        if value.numerator.bit_length() > 2048 or value.denominator.bit_length() > 2048:
            raise ValueError('Arithmetic magnitude limit')
        return value
    try:
        result = evaluate(tree.body)
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError('Undefined or out-of-range arithmetic') from exc
    return {'status': 'calculated', 'expression': expression, 'exact': str(result),
            'method': 'rational-arithmetic/1', 'stored_as_premise': False}
