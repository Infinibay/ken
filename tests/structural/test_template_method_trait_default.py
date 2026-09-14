"""Template Method ``trait-default``: a Rust trait default calling an overridden hook.

The variant is a published rule, so the test goes through the registry name
``template-method#trait-default`` rather than a private copy of the query.

The query counts concrete implementations: a hook implemented by a single type
does not satisfy the contract.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'template-method#trait-default'

POSITIVE = '''pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn finish(&self, value: i32) -> i32;
    fn run(&self) -> i32 {
        let carried = self.prepare();
        self.finish(carried)
    }
}

pub struct Alpha;

impl Pipeline for Alpha {
    fn prepare(&self) -> i32 { 1 }
    fn finish(&self, value: i32) -> i32 { value + 1 }
}

pub struct Beta;

impl Pipeline for Beta {
    fn prepare(&self) -> i32 { 2 }
    fn finish(&self, value: i32) -> i32 { value * 2 }
}
'''

NO_DEFAULT = '''pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn finish(&self, value: i32) -> i32;
}
pub struct Alpha;
impl Pipeline for Alpha {
    fn prepare(&self) -> i32 { 1 }
    fn finish(&self, value: i32) -> i32 { value + 1 }
}
'''

DEAD_HOOK = '''pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn run(&self) -> i32 { 7 }
}
pub struct Alpha;
impl Pipeline for Alpha { fn prepare(&self) -> i32 { 1 } }
pub struct Beta;
impl Pipeline for Beta { fn prepare(&self) -> i32 { 2 } }
'''

NEVER_OVERRIDDEN = '''pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn run(&self) -> i32 { self.prepare() }
}
'''

FREE_FUNCTION = '''fn helper() -> i32 { 3 }
pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn run(&self) -> i32 { helper() }
}
pub struct Alpha;
impl Pipeline for Alpha { fn prepare(&self) -> i32 { 1 } }
pub struct Beta;
impl Pipeline for Beta { fn prepare(&self) -> i32 { 2 } }
'''

SINGLE_IMPLEMENTATION = '''pub trait Pipeline {
    fn prepare(&self) -> i32;
    fn run(&self) -> i32 { self.prepare() }
}
pub struct Alpha;
impl Pipeline for Alpha { fn prepare(&self) -> i32 { 1 } }
'''

RENAMED = '''pub trait Conveyor {
    fn alpha(&self) -> i32;
    fn beta(&self, value: i32) -> i32;
    fn gamma(&self) -> i32 {
        let carried = self.alpha();
        self.beta(carried)
    }
}
pub struct First;
impl Conveyor for First {
    fn alpha(&self) -> i32 { 1 }
    fn beta(&self, value: i32) -> i32 { value }
}
pub struct Second;
impl Conveyor for Second {
    fn alpha(&self) -> i32 { 2 }
    fn beta(&self, value: i32) -> i32 { value }
}
'''


def detect(source):
    graph = link_project([lower_source(source, 'rust', 'pipeline.rs')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


def test_default_algorithm_calling_two_overridden_hooks_is_detected():
    matches = detect(POSITIVE)
    # One match per hook of the default algorithm, each implemented twice.
    assert len(matches) == 2
    hooks = {m['bindings']['$hook'].rsplit('/', 1)[-1] for m in matches}
    assert hooks == {'CALLABLE:prepare@25', 'CALLABLE:finish@55'}
    for match in matches:
        bindings = match['bindings']
        assert bindings['$unit'].endswith('/INTERFACE:Pipeline')
        assert bindings['$algorithm'].endswith('/CALLABLE:run@96')


def test_renamed_trait_and_hooks_preserve_detection():
    matches = detect(RENAMED)
    assert len(matches) == 2
    assert {m['bindings']['$unit'].rsplit('/', 1)[-1] for m in matches} == {'INTERFACE:Conveyor'}


def test_trait_without_a_default_method_is_rejected():
    assert not detect(NO_DEFAULT)


def test_default_that_does_not_call_the_hook_is_rejected():
    assert not detect(DEAD_HOOK)


def test_hook_never_overridden_is_rejected():
    assert not detect(NEVER_OVERRIDDEN)


def test_default_calling_a_free_function_is_rejected():
    """A call target outside the trait is not an extension slot."""
    assert not detect(FREE_FUNCTION)


def test_hook_implemented_by_a_single_type_is_rejected():
    """The contract asks for the hook to be implemented by more than one type."""
    assert not detect(SINGLE_IMPLEMENTATION)


def test_variant_is_ready_for_its_single_declared_language():
    rule = next(r for r in _load_catalog() if r.id == 'template-method')
    row = next(v for v in rule.variants if v['id'] == 'trait-default')
    assert row['languages'] == ['rust']
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'OVERRIDES' in row['query'] and 'count distinct' in row['query']
