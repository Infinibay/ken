"""Authored creation algorithms are checked independently of their union roots."""
import pytest
from .test_gof_executable import evaluate
from .test_algorithm_prototype import source as prototype_source, LANGUAGES
from .test_algorithm_builder import IMMUTABLE

@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['', 'constant-input', 'return-original', 'different-result', 'ignored-input'])
def test_explicit_copy_keeps_constructor_input_and_return_identity(language, mutation):
    assert bool(evaluate(prototype_source(language, mutation), language, 'prototype#explicit-copy')) is (mutation == '')

@pytest.mark.parametrize('language', IMMUTABLE)
def test_persistent_builder_returns_state_carrying_successor(language):
    assert evaluate(IMMUTABLE[language], language, 'builder#immutable-product')

@pytest.mark.parametrize('language', LANGUAGES)
def test_copy_rejects_a_replaced_allocation_after_independent_work(language):
    text = prototype_source(language)
    if language == 'python':
        text=text.replace('return result', 'result = Product(0)\n        return result')
    else:
        text=text.replace('return result', 'result = new Product(0); return result')
    assert not evaluate(text, language, 'prototype#explicit-copy')
