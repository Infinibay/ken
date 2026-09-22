"""Interpreter algorithm contracts, including explicit unmet semantic expectations.

Known structural-signature false positives are strict xfails against the desired
algorithm contract. They must become passing rejection tests when the matcher
learns result consumption/context correlation; they are not successful coverage.
"""
from __future__ import annotations

import pytest

from .contract_support import contract_matches

from .test_gof_executable import evaluate

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: str = 'both') -> str:
    """A sum grammar node: evaluate two child expressions, combine their values."""
    receiver = 'self' if language == 'python' else 'this'
    context_left = '0' if mutation == 'both-contexts' else 'context'
    context_right = '0' if mutation in {'both-contexts', 'right-context'} else 'context'
    if mutation == 'both-origins':
        context_left = context_right = 'other'
    left = f'{receiver}.left.evaluate({context_left})'
    right = f'{receiver}.right.evaluate({context_right})'
    result = 'a + b'
    if mutation == 'discard-left':
        result = 'b'
    elif mutation == 'discard-both':
        result = '0'
    elif mutation == 'wrong-combine':
        result = 'a - b'
    elif mutation == 'overwrite-result':
        right += '\n        b = 0' if language == 'python' else '; b = 0'
    elif mutation == 'no-recursion':
        left = right = 'context'
    if language == 'python':
        before = '        audit = 17 + 3\n        print(audit)\n' if noise in {'before', 'both'} else ''
        between = '        independent = 9 * 2\n        print(independent)\n' if noise in {'between', 'both'} else ''
        return f'''class Expression:
    def evaluate(self, context):
        raise NotImplementedError()
class Literal(Expression):
    def __init__(self, value): self.value = value
    def evaluate(self, context): return self.value
class Sum(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    def evaluate(self, context):
{before}        other = 42
        a = {left}
{between}        b = {right}
        return {result}
'''
    before = ''
    between = ''
    if language == 'java':
        if noise in {'before', 'both'}:
            before = 'int audit = 17 + 3; System.out.println(audit);'
        if noise in {'between', 'both'}:
            between = 'int independent = 9 * 2; System.out.println(independent);'
        return f'''interface Expression {{ int evaluate(int context); }}
class Literal implements Expression {{
    int value;
    Literal(int value) {{ this.value = value; }}
    public int evaluate(int context) {{ return this.value; }}
}}
class Sum implements Expression {{
    Expression left; Expression right;
    Sum(Expression left, Expression right) {{ this.left = left; this.right = right; }}
    public int evaluate(int context) {{
        {before}
        int other = 42;
        int a = {left};
        {between}
        int b = {right};
        return {result};
    }}
}}
'''
    if noise in {'before', 'both'}:
        before = 'const audit = 17 + 3; console.log(audit);'
    if noise in {'between', 'both'}:
        between = 'const independent = 9 * 2; console.log(independent);'
    return f'''interface Expression {{ evaluate(context: number): number; }}
class Literal implements Expression {{
    value: number;
    constructor(value: number) {{ this.value = value; }}
    evaluate(context: number): number {{ return this.value; }}
}}
class Sum implements Expression {{
    left: Expression; right: Expression;
    constructor(left: Expression, right: Expression) {{ this.left = left; this.right = right; }}
    evaluate(context: number): number {{
        {before}
        const other = 42;
        const a = {left};
        {between}
        let b = {right};
        return {result};
    }}
}}
'''


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', ['none', 'before', 'between', 'both'])
def test_sum_interpreter_tolerates_independent_work(language, noise):
    matches = evaluate(source(language, noise=noise), language, 'interpreter')
    assert matches


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['both-contexts', 'both-origins', 'no-recursion'])
def test_sum_interpreter_rejects_missing_context_origin_or_recursion(language, mutation):
    assert not evaluate(source(language, mutation), language, 'interpreter')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['right-context', 'discard-left', 'discard-both', 'overwrite-result'])
def test_desired_pure_binary_contract_requires_all_contexts_and_result_consumption(language, mutation):
    assert contract_matches(source(language), language, 'interpreter.binary_result')
    assert not contract_matches(source(language, mutation), language, 'interpreter.binary_result')


@pytest.mark.parametrize('language', LANGUAGES)
def test_another_binary_grammar_is_still_an_interpreter(language):
    # Operator identity belongs to a specific grammar, not the GoF category.
    assert evaluate(source(language, 'wrong-combine'), language, 'interpreter')
