"""Prototype ``language-copy``: the copy comes from the language's own mechanism.

The variant is a published rule, so the test goes through the registry name
``prototype#language-copy`` rather than a private copy of the query.

The three ready neighbours all describe a *hand-written* copy: a same-named field
copy, an explicit construction receiving instance state, or a derived ``Clone``.
This variant is the other half of the ficha ("resolver protocolo, constructor de copia
o derive"): the copy is produced by whatever the language itself provides, and that is
a different mechanism in each of the five declared languages.

  python   copy.deepcopy(self)          a standard-library copier
  java     (Config) super.clone()       Object.clone through Cloneable
  csharp   this.MemberwiseClone()       the framework's member-wise copy
  cpp      Config(const Config&)        the language's copy constructor
  rust     fn clone(&self) -> Self      the Clone trait's required method

Two false positives were measured and closed rather than documented:

* a C++ **move** constructor ``Config(Config&&)`` matched the copy-constructor branch,
  because the parameter's type resolves to the same class either way. The reference
  kind is now recorded on the parameter (IR 1.60) and the branch requires an lvalue
  reference, which also excludes a by-value ``Config(Config)``.
* a Rust ``fn clone`` returning a **fresh** value matched, because returning a new
  instance of the type is not the same as copying the receiver. The branch now
  requires the returned construction to be initialized from a field of that type.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'prototype#language-copy'
LANGUAGES = ['python', 'java', 'csharp', 'cpp', 'rust']
EXTENSIONS = {'python': 'py', 'java': 'java', 'csharp': 'cs', 'cpp': 'cpp', 'rust': 'rs'}


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'prototype')
    return next(v for v in rule.variants if v['id'] == 'language-copy')


def positive(language, type_name='Config', method='duplicate'):
    if language == 'python':
        return (f'import copy\n\nclass {type_name}:\n    def __init__(self):\n        self.value = 1\n\n'
                f'    def {method}(self):\n        return copy.deepcopy(self)\n')
    if language == 'java':
        return (f'class {type_name} implements Cloneable {{\n    private int value;\n\n'
                f'    public {type_name} {method}() {{\n'
                f'        return ({type_name}) super.clone();\n    }}\n}}\n')
    if language == 'csharp':
        return (f'class {type_name} {{\n    private int value;\n\n'
                f'    public {type_name} {method}() {{\n'
                f'        return ({type_name}) this.MemberwiseClone();\n    }}\n}}\n')
    if language == 'cpp':
        return (f'class {type_name} {{\n    int value;\npublic:\n'
                f'    {type_name}() : value(1) {{}}\n'
                f'    {type_name}(const {type_name}& other) : value(other.value) {{}}\n}};\n')
    # Rust names the trait method; only the type can be renamed.
    return (f'struct {type_name} {{ value: i32 }}\n\n'
            f'impl Clone for {type_name} {{\n'
            f'    fn clone(&self) -> {type_name} {{\n'
            f'        {type_name} {{ value: self.value }}\n    }}\n}}\n')


PY_ALIAS = '''import copy

class Config:
    def __init__(self):
        self.value = 1

    def duplicate(self):
        return self
'''

PY_FRESH = '''import copy

class Config:
    def __init__(self):
        self.value = 1

    def duplicate(self):
        return Config()
'''

JAVA_FRESH = '''class Config implements Cloneable {
    private int value;

    public Config duplicate() {
        return new Config();
    }
}
'''

CSHARP_FRESH = '''class Config {
    private int value;

    public Config Duplicate() {
        return new Config();
    }
}
'''

CPP_NONCOPY = '''class Config {
    int value;
public:
    Config(int start) : value(start) {}
};
'''

CPP_MOVE = '''class Config {
    int value;
public:
    Config() : value(1) {}
    Config(Config&& other) : value(other.value) {}
};
'''

CPP_BY_VALUE = '''class Config {
    int value;
public:
    Config(Config other) : value(other.value) {}
};
'''

CPP_BOTH_REFERENCES = '''class Config {
    int value;
public:
    Config() : value(1) {}
    Config(const Config& other) : value(other.value) {}
    Config(Config&& other) : value(other.value) {}
};
'''

RUST_OTHER_METHOD = '''struct Config { value: i32 }

impl Config {
    fn make(&self) -> Config {
        Config { value: 0 }
    }
}
'''

RUST_CLONE_FRESH = '''struct Config { value: i32 }

impl Clone for Config {
    fn clone(&self) -> Config {
        Config { value: 0 }
    }
}
'''

# The false-positive family measured on real projects: the copy primitive is applied
# to a container that is not the object. ``os.environ.copy()``, a set's ``.copy()``,
# a tensor's ``.clone()`` and ``deepcopy(self.rows.get(key))`` are all ordinary
# container duplication inside a method of the class, not a copy of the class.
PY_FOREIGN_CONTAINER = '''class Config:
    def __init__(self):
        self.items = []

    def duplicate(self):
        return self.items.copy()
'''

PY_ENVIRONMENT = '''import os

class Config:
    def environment(self):
        return os.environ.copy()
'''

PY_FIELD_DEEPCOPY = '''import copy

class Config:
    def __init__(self):
        self.rows = {}

    def restore(self, key):
        return copy.deepcopy(self.rows.get(key))
'''

JAVA_FIELD_CLONE = '''class Config implements Cloneable {
    private Object items;

    public Object duplicate() {
        return this.items.clone();
    }
}
'''

CSHARP_FIELD_CLONE = '''class Config {
    private object items;

    public object Duplicate() {
        return this.items.Clone();
    }
}
'''

JAVA_BASE_CLONE = '''class Config implements Cloneable {
    private int value;

    public Config duplicate() {
        return (Config) super.clone();
    }
}
'''


def detect(language, source):
    graph = link_project([lower_source(source, language, f'prototype.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_language_copy_mechanism_is_detected(language):
    matches = detect(language, positive(language))
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role with the sibling variants is the copied type.
    assert '/CLASS:Config' in bindings['$unit']
    assert '/CALLABLE:' in bindings['$witness']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_the_type_preserves_detection(language):
    assert detect(language, positive(language, type_name='Registry', method='acquire'))


def test_returning_the_receiver_is_not_a_copy():
    assert not detect('python', PY_ALIAS)


def test_returning_a_fresh_instance_is_not_a_copy():
    assert not detect('python', PY_FRESH)
    assert not detect('java', JAVA_FRESH)
    assert not detect('csharp', CSHARP_FRESH)


def test_a_constructor_taking_another_type_is_not_a_copy_constructor():
    assert not detect('cpp', CPP_NONCOPY)


def test_a_move_constructor_is_not_a_copy_constructor():
    """``X(X&&)`` binds the move protocol; the parameter type resolves the same."""
    assert not detect('cpp', CPP_MOVE)


def test_a_by_value_constructor_is_not_a_copy_constructor():
    assert not detect('cpp', CPP_BY_VALUE)


def test_a_method_that_is_not_the_clone_protocol_is_rejected():
    assert not detect('rust', RUST_OTHER_METHOD)


def test_a_clone_returning_a_fresh_value_is_rejected():
    assert not detect('rust', RUST_CLONE_FRESH)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'reference_kind' in row['query'] and 'STORES_VALUE' in row['query']


def test_cpp_reference_kind_separates_the_copy_from_the_move():
    """IR 1.60: the declarator spelling is the only place the two differ."""
    graph = link_project([lower_source(CPP_BOTH_REFERENCES, 'cpp', 'prototype.cpp')])
    assert not graph.diagnostics, graph.diagnostics
    kinds = sorted(e.attrs.get('reference_kind') for e in graph.entities.values()
                   if e.kind == 'PARAMETER')
    assert kinds == ['lvalue', 'rvalue'], kinds

def test_copying_a_foreign_container_is_not_a_copy_of_the_object():
    """The primitive is identified by name, so the branch also requires that what is
    copied is the instance itself; otherwise every ``.copy()``/``.clone()`` on a
    dictionary, a set, an environment mapping or a tensor inside a method matched."""
    assert not detect('python', PY_FOREIGN_CONTAINER)
    assert not detect('python', PY_ENVIRONMENT)
    assert not detect('python', PY_FIELD_DEEPCOPY)
    assert not detect('java', JAVA_FIELD_CLONE)
    assert not detect('csharp', CSHARP_FIELD_CLONE)


def test_an_inherited_clone_is_still_the_instance():
    """``super.clone()`` calls the inherited member on *this* object, so the Java
    spelling of the protocol keeps matching."""
    assert detect('java', JAVA_BASE_CLONE)
