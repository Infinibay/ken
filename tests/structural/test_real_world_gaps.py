"""Authored reductions of gaps reviewed in real repositories.

These previously failed as strict xfails; they now exercise canonical queries.
Provenance and reviewed source locations: docs/structural-validation/2026-09-12/README.md.
"""
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


def matches(source, rule):
    registry = builtin_rules()
    selected = next((r for r in registry if r.id == rule), None)
    if selected is None:
        selected = named_rule(rule, registry)
    return execute_rules(link_project([lower_source(source.encode(), 'python', 'sample.py')]), [selected], registry=registry)['matches']


def test_cleanup_is_not_observer():
    assert not matches('''
class Resources:
    def __init__(self):
        self.files = []
    def close(self):
        for file in self.files:
            file.close()
''', 'observer')


def test_callback_subscription_is_observer():
    assert matches('''
class Events:
    def __init__(self):
        self.handlers = []
    def subscribe(self, handler):
        self.handlers.append(handler)
    def publish(self, value):
        for handler in self.handlers:
            handler(value)
''', 'observer')


def test_delegated_python_cursor():
    assert matches('''
class Forward:
    def __init__(self, iterable):
        self.cursor = iter(iterable)
    def __iter__(self):
        return self
    def __next__(self):
        return next(self.cursor)
''', 'gof.iterator')
