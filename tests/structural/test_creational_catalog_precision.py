"""Executable catalog contracts: evidence must belong to the returned algorithm.

Each mutation retains the convincing but unrelated operation. The oracle labels
the program positive or negative; detector disagreements are ordinary failures.
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project

from . import test_builder_immutable_product as immutable
from . import test_factory_method_contract_slot as factory_contract
from . import test_flyweight_entry_api as entries
from . import test_prototype_language_copy as copying
from . import test_singleton_once_primitive as once
from . import test_singleton_module_shared as shared
from . import test_algorithm_flyweight as interning


@pytest.fixture(scope='module')
def registry():
    return query_registry(builtin_rules())


def search(registry, target, language, source):
    if language == 'python':
        compile(source, '<creational-precision>', 'exec')
    graph = link_project([lower_source(source, language, 'precision.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    result = Engine(query_graph(graph), registry,
                    QueryBudget(max_matches=200, max_rows=500000,
                                max_states=100000, timeout_ms=3000), 'strict').execute(registry[target])
    assert result['complete'], result
    return result['matches']


@pytest.mark.parametrize('language', immutable.LANGUAGES)
@pytest.mark.parametrize('discarded', [False, True])
def test_builder_successor_must_be_the_construction_that_receives_state(registry, language, discarded):
    source = immutable.source(language, immutable.BODY[language])
    if discarded:
        if language == 'python':
            source = source.replace('return Builder(name, self.size)',
                                    'Builder(name, self.size)\n        return Builder(0, 0)')
        elif language in {'java', 'csharp', 'javascript', 'typescript'}:
            source = source.replace('return new Builder(name, this.size);',
                                    'new Builder(name, this.size); return new Builder(0, 0);')
        elif language == 'cpp':
            source = source.replace('return Builder(name, this->size);',
                                    'Builder(name, this->size); return Builder(0, 0);')
        elif language == 'go':
            source = source.replace('return Builder{name: name, size: b.size}',
                                    '_ = Builder{name: name, size: b.size}; return Builder{name: 0, size: 0}')
        else:
            source = source.replace('Builder { name: name, size: self.size }',
                                    'let _ = Builder { name: name, size: self.size }; Builder { name: 0, size: 0 }')
    assert bool(search(registry, 'builder#immutable-product', language, source)) is not discarded


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('shared_contract', [False, True])
def test_abstract_factory_product_slots_belong_to_one_contract(registry, language, shared_contract):
    if language == 'python':
        source = '''class First: pass
class Second: pass
class P(First): pass
class Q(Second): pass
class A:
 def one(self): pass
class B:
 def two(self): pass
class Concrete(A, B):
 def one(self): return P()
 def two(self): return Q()
'''
        if shared_contract:
            source = source.replace(' def one(self): pass', ' def one(self): pass\n def two(self): pass')
    elif language == 'java':
        source = '''class First {} class Second {} class P extends First {} class Q extends Second {}
interface A { First one(); } interface B { Second two(); }
class Concrete implements A, B {
 public First one() { return new P(); }
 public Second two() { return new Q(); }
}'''
        if shared_contract:
            source = source.replace('First one();', 'First one(); Second two();')
    else:
        source = '''class First {} class Second {} class P extends First {} class Q extends Second {}
interface A { one(): First; } interface B { two(): Second; }
class Concrete implements A, B {
 one(): First { return new P(); }
 two(): Second { return new Q(); }
}'''
        if shared_contract:
            source = source.replace('one(): First;', 'one(): First; two(): Second;')
    assert bool(search(registry, 'abstract-factory#nominal-families', language, source)) is shared_contract


@pytest.mark.parametrize('language', ['go', 'rust'])
def test_factory_role_is_concrete_implementation_for_named_query_composition(registry, language):
    source = factory_contract.GO if language == 'go' else factory_contract.RUST
    matches = search(registry, 'factory-method#contract-slot', language, source)
    assert matches
    for match in matches:
        roles = match['bindings']
        assert roles['$factory'] != roles['$slot']
        assert roles['$factory'].startswith(roles['$concrete'] + '/')


@pytest.mark.parametrize('always_throw', [False, True])
def test_cpp_copy_constructor_needs_normal_completion(registry, always_throw):
    source = copying.positive('cpp')
    if always_throw:
        source = source.replace('value(other.value) {}', 'value(other.value) { throw 1; }')
    assert bool(search(registry, 'prototype#language-copy', 'cpp', source)) is not always_throw


@pytest.mark.parametrize('replaces', [False, True])
def test_cpp_interning_api_preserves_existing_entries(registry, replaces):
    source = entries.SOURCES['cpp']
    if replaces:
        source = source.replace('try_emplace(key, key)', 'insert_or_assign(key, Value(key))')
    assert bool(search(registry, 'flyweight#entry-api', 'cpp', source)) is not replaces


@pytest.mark.parametrize('language', ['python', 'java', 'csharp'])
@pytest.mark.parametrize('discarded', [False, True])
def test_primitive_copy_result_must_be_returned(registry, language, discarded):
    source = copying.positive(language)
    if discarded:
        if language == 'python':
            source = source.replace('return copy.deepcopy(self)',
                                    'copy.deepcopy(self)\n        return self')
        elif language == 'java':
            source = source.replace('return (Config) super.clone();',
                                    'super.clone(); return this;')
        else:
            source = source.replace('return (Config) this.MemberwiseClone();',
                                    'this.MemberwiseClone(); return this;')
    assert bool(search(registry, 'prototype#language-copy', language, source)) is not discarded


@pytest.mark.parametrize('expression,expected', [
    ('prev != null ? prev : new Config()', True),
    ('prev == null ? new Config() : prev', True),
    ('new Config()', False),
    ('prev != null ? new Config() : new Config()', False),
    ('prev != null ? new Config() : prev', False),
])
def test_atomic_update_retains_existing_value_and_initializes_only_the_missing_arm(registry, expression, expected):
    source = once.source('java', 'positive').replace('prev != null ? prev : new Config()', expression)
    assert bool(search(registry, 'singleton#once-primitive', 'java', source)) is expected


@pytest.mark.parametrize('language,old,new', [
    ('go', '.Do(', '.Repeat('),
    ('cpp', 'std::call_once(', 'invoke('),
    ('rust', '.get_or_init(', '.replace_with('),
    ('java', '.updateAndGet(', '.map('),
    ('csharp', 'Lazy<Config>', 'Factory<Config>'),
])
def test_arbitrary_callback_api_is_not_a_once_primitive(registry, language, old, new):
    source = once.source(language, 'positive').replace(old, new)
    assert not search(registry, 'singleton#once-primitive', language, source)


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript', 'cpp', 'go'])
@pytest.mark.parametrize('reassigned', [False, True])
def test_module_shared_storage_has_one_explicit_write(registry, language, reassigned):
    source = shared.source(language, 'positive')
    if reassigned:
        if language == 'python':
            source += '\nshared = Config()\n'
        elif language in {'javascript', 'typescript'}:
            # The original declaration is const; use let for a valid reset example.
            source = source.replace('const shared', 'let shared') + '\nshared = new Config();\n'
        elif language == 'cpp':
            source = source.replace('return shared;', 'shared = Config(); return shared;')
        else:
            source += '\nfunc Reset() { shared = Config{value: 2} }\n'
    assert bool(search(registry, 'singleton#module-shared', language, source)) is not reassigned


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('miss', [False, True])
def test_flyweight_insertion_branch_has_the_missing_entry_polarity(registry, language, miss):
    source = interning.source(language)
    if not miss:
        source = source.replace('key not in self.pool', 'key in self.pool')
        source = source.replace('this.pool[key] == null', 'this.pool[key] != null')
        source = source.replace('this.pool[key] === undefined', 'this.pool[key] !== undefined')
    assert bool(search(registry, 'flyweight#explicit-interning', language, source)) is miss


@pytest.mark.parametrize('copy_state', [False, True])
def test_cpp_copy_constructor_copies_state_instead_of_only_matching_a_signature(registry, copy_state):
    source = copying.positive('cpp')
    if not copy_state:
        source = source.replace('value(other.value)', 'value(0)')
    assert bool(search(registry, 'prototype#language-copy', 'cpp', source)) is copy_state


def test_lazy_singleton_write_after_the_guard_is_unconditional(registry):
    source = '''class Shared:
 value = None
 @classmethod
 def get(cls):
  if cls.value is None:
   metric = 1 + 2
  cls.value = Shared()
  return cls.value
'''
    assert not search(registry, 'singleton#lazy-guarded', 'python', source)
