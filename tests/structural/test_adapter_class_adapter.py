"""Adapter ``class-adapter``: adaptation by inheriting the adaptee, not by holding it.

The variant is a published rule, so the test goes through the registry name
``adapter#class-adapter``.

The class must inherit two distinct bases: the target contract whose slot it
overrides, and the adaptee whose operation the override actually calls.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'adapter#class-adapter'

PY = '''class Target:
    def request(self):
        return 0

class Adaptee:
    def specific(self):
        return 1

class Adapter(Target, Adaptee):
    def request(self):
        return self.specific()
'''

PY_RENAMED = '''class Contract:
    def invoke(self):
        return 0

class Legacy:
    def legacy_call(self):
        return 1

class Bridge(Contract, Legacy):
    def invoke(self):
        return self.legacy_call()
'''

# The classic object adapter: the adaptee is held in a field, not inherited.
PY_OBJECT_ADAPTER = '''class Target:
    def request(self):
        return 0

class Adaptee:
    def specific(self):
        return 1

class Adapter(Target):
    def __init__(self, adaptee: Adaptee):
        self.adaptee = adaptee
    def request(self):
        return self.adaptee.specific()
'''

PY_NO_DELEGATION = '''class Target:
    def request(self):
        return 0

class Adaptee:
    def specific(self):
        return 1

class Adapter(Target, Adaptee):
    def request(self):
        return 7
'''

PY_SINGLE_BASE = '''class Target:
    def request(self):
        return 0

class Adapter(Target):
    def request(self):
        return 0
'''

CPP = '''struct Target { virtual int request() = 0; virtual ~Target() = default; };
struct Adaptee { int specific() { return 1; } };
struct Adapter : Target, Adaptee {
  int request() override { return this->specific(); }
};
'''

CPP_RENAMED = '''struct Contract { virtual int invoke() = 0; virtual ~Contract() = default; };
struct Legacy { int legacy_call() { return 1; } };
struct Bridge : Contract, Legacy {
  int invoke() override { return this->legacy_call(); }
};
'''

CPP_NO_DELEGATION = '''struct Target { virtual int request() = 0; virtual ~Target() = default; };
struct Adaptee { int specific() { return 1; } };
struct Adapter : Target, Adaptee {
  int request() override { return 7; }
};
'''

CPP_SINGLE_BASE = '''struct Target { virtual int request() = 0; virtual ~Target() = default; };
struct Adapter : Target {
  int request() override { return 7; }
};
'''

PATHS = {'python': 'a.py', 'cpp': 'a.cpp'}


def detect(language, source):
    graph = link_project([lower_source(source, language, PATHS[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(PATHS))
def test_class_inheriting_both_contract_and_adaptee_is_detected(language):
    source = PY if language == 'python' else CPP
    matches = detect(language, source)
    assert len(matches) == 1
    bindings = matches[0]['bindings']
    assert bindings['$unit'].endswith('/CLASS:Adapter')
    assert bindings['$target'] != bindings['$adaptee']
    assert bindings['$override'] != bindings['$slot']
    assert bindings['$delegate'] != bindings['$slot']


def test_renamed_bases_and_operations_preserve_detection():
    for language, source in (('python', PY_RENAMED), ('cpp', CPP_RENAMED)):
        matches = detect(language, source)
        assert len(matches) == 1, language


def test_object_adapter_holding_the_adaptee_is_rejected():
    """Adaptation by field is the other variant, not this one."""
    assert not detect('python', PY_OBJECT_ADAPTER)


@pytest.mark.parametrize('language', sorted(PATHS))
def test_class_not_calling_the_adaptee_operation_is_rejected(language):
    source = PY_NO_DELEGATION if language == 'python' else CPP_NO_DELEGATION
    assert not detect(language, source)


@pytest.mark.parametrize('language', sorted(PATHS))
def test_class_with_a_single_base_is_rejected(language):
    source = PY_SINGLE_BASE if language == 'python' else CPP_SINGLE_BASE
    assert not detect(language, source)


def test_variant_is_ready_for_both_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'adapter')
    row = next(v for v in rule.variants if v['id'] == 'class-adapter')
    assert row['languages'] == ['python', 'cpp']
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'SUBTYPE_OF' in row['query'] and 'OVERRIDES' in row['query']
