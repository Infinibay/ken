"""Prototype contracts: state origin, fresh result and explicit sharing policy."""
from __future__ import annotations

import pytest

from .test_gof_executable import evaluate

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: str = 'both', mutable: bool = False) -> str:
    receiver = 'self' if language == 'python' else 'this'
    captured = '0' if mutation == 'constant-input' else receiver + '.state'
    stored = '0' if mutation == 'ignored-input' else 'state'
    returned = receiver if mutation == 'return-original' else 'result'
    if language == 'python':
        before = '        audit = 17 * 3\n        print(audit)\n' if noise in {'before', 'both'} else ''
        after = '        independent = 9 + 1\n        print(independent)\n' if noise in {'after', 'both'} else ''
        overwrite = '        result = Product(0)\n' if mutation == 'different-result' else ''
        return f'''class Product:
    def __init__(self, state):
        self.state = {stored}
    def duplicate(self):
{before}        result = Product({captured})
{after}{overwrite}        return {returned}

def exercise():
    original = Product({'[1]' if mutable else '1'})
    original.state{'[0]' if mutable else ''} = 7
    duplicate = original.duplicate()
    duplicate.state{'[0]' if mutable else ''} = 99
'''
    if language == 'java':
        field_type = 'int[]' if mutable else 'int'
        before = 'int audit = 17 * 3; System.out.println(audit);' if noise in {'before', 'both'} else ''
        after = 'int independent = 9 + 1; System.out.println(independent);' if noise in {'after', 'both'} else ''
        overwrite = 'result = new Product(0);' if mutation == 'different-result' else ''
        return f'''class Product {{
    {field_type} state;
    Product({field_type} state) {{ this.state = {stored}; }}
    Product duplicate() {{
        {before} Product result = new Product({captured});
        {after} {overwrite} return {returned};
    }}
}}
class Exercise {{
    void run() {{
        Product original = new Product({'new int[]{1}' if mutable else '1'});
        original.state{'[0]' if mutable else ''} = 7;
        Product duplicate = original.duplicate();
        duplicate.state{'[0]' if mutable else ''} = 99;
    }}
}}
'''
    field_type = 'number[]' if mutable else 'number'
    before = 'const audit = 17 * 3; console.log(audit);' if noise in {'before', 'both'} else ''
    after = 'const independent = 9 + 1; console.log(independent);' if noise in {'after', 'both'} else ''
    overwrite = 'result = new Product(0);' if mutation == 'different-result' else ''
    return f'''class Product {{
    state: {field_type};
    constructor(state: {field_type}) {{ this.state = {stored}; }}
    duplicate(): Product {{
        {before} let result = new Product({captured});
        {after} {overwrite} return {returned};
    }}
}}
function exercise() {{
    const original = new Product({'[1]' if mutable else '1'});
    original.state{'[0]' if mutable else ''} = 7;
    const duplicate = original.duplicate();
    duplicate.state{'[0]' if mutable else ''} = 99;
}}
'''


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', ['none', 'before', 'after', 'both'])
def test_prototype_tolerates_independent_work(language, noise):
    assert evaluate(source(language, noise=noise), language, 'prototype')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['constant-input', 'return-original', 'different-result'])
def test_prototype_rejects_wrong_origin_or_returned_identity(language, mutation):
    assert not evaluate(source(language, mutation), language, 'prototype')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='explicit-copy correlates constructor argument but not retained constructor state; algorithms/prototype.md')
def test_prototype_requires_constructor_to_retain_captured_state(language):
    assert not evaluate(source(language, 'ignored-input'), language, 'prototype')


@pytest.mark.parametrize('language', LANGUAGES)
def test_shallow_shared_state_is_a_valid_prototype_policy(language):
    assert evaluate(source(language, mutable=True), language, 'prototype')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Stronger independent-state contract: shallow array reference copy shares later writes; generic Prototype permits sharing')
def test_desired_independent_state_contract_rejects_shared_array(language):
    assert not evaluate(source(language, mutable=True), language, 'prototype')
