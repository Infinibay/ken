"""Stored callable policies without nominal subtype hierarchies."""
import pytest
from .test_gof_executable import evaluate

SOURCES = {
 'python': 'class Context:\n def configure(self, supplied): self.policy = supplied\n def apply(self, value): return self.policy(value)\n',
 'javascript': 'class Context { configure(supplied) { this.policy = supplied; } apply(value) { return this.policy(value); } }',
 'typescript': 'class Context { policy: (x: number) => number; configure(supplied: (x: number) => number) { this.policy = supplied; } apply(value: number) { return this.policy(value); } }',
 'go': 'package sample; type Context struct { policy func(int) int }; func(c *Context) configure(supplied func(int) int) { c.policy = supplied }; func(c *Context) apply(value int) int { return c.policy(value) }',
}


@pytest.mark.parametrize('language', SOURCES)
def test_stored_function_strategy(language):
    assert evaluate(SOURCES[language], language, 'strategy')
    assert evaluate(SOURCES[language].replace('Context', 'Pricing').replace('policy', 'discount'), language, 'strategy')


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('old,new', [
 ('policy(value)', 'other(value)'),
 ('policy(value)', 'policy'),
 ('policy = supplied', 'other = supplied'),
])
def test_stored_function_requires_injection_and_invocation_of_same_field(language, old, new):
    assert not evaluate(SOURCES[language].replace(old, new), language, 'strategy')
