"""Factory Method ``contract-slot``: a client calls the creation slot it was given.

The variant is a published rule, so the test goes through the registry name
``factory-method#contract-slot``.

Go and Rust have no inheritance: Go satisfies an interface by method set
(``IMPLEMENTS``) and Rust by a trait impl (``SUBTYPE_OF``), so the query accepts
either edge. The client's call must resolve to the slot the contract declares,
which is what makes this a contract slot rather than a concrete constructor.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'factory-method#contract-slot'

GO = '''package factory

type Product struct{ Name string }

type Creator interface {
	Create() Product
}

type ConcreteCreator struct{}

func (ConcreteCreator) Create() Product { return Product{Name: "x"} }

func Client(c Creator) Product {
	return c.Create()
}
'''

GO_INCOMPLETE_INTERFACE = '''package factory

type Product struct{ Name string }

type Creator interface {
	Create() Product
	Label() string
}

type ConcreteCreator struct{}

func (ConcreteCreator) Create() Product { return Product{Name: "x"} }

func Client(c Creator) Product {
	return c.Create()
}
'''

GO_CLIENT_IGNORES_SLOT = '''package factory

type Product struct{ Name string }

type Creator interface {
	Create() Product
}

type ConcreteCreator struct{}

func (ConcreteCreator) Create() Product { return Product{Name: "x"} }

var shared Product

func Client(c Creator) Product {
	return shared
}
'''

GO_OTHER_CONTRACT = '''package factory

type Product struct{ Name string }
type Other struct{ Name string }

type Creator interface {
	Create() Product
}

type OtherContract interface {
	Create() Other
}

type ConcreteCreator struct{}

func (ConcreteCreator) Create() Other { return Other{Name: "x"} }

func Client(c Creator) Product {
	return Product{}
}
'''

RUST = '''pub trait Creator {
    fn create(&self) -> Product;
}

pub struct Product {
    pub name: i32,
}

pub struct ConcreteCreator;

impl Creator for ConcreteCreator {
    fn create(&self) -> Product {
        Product { name: 1 }
    }
}

pub fn client(creator: &dyn Creator) -> Product {
    creator.create()
}
'''

RUST_CLIENT_IGNORES_SLOT = '''pub trait Creator {
    fn create(&self) -> Product;
}

pub struct Product {
    pub name: i32,
}

pub struct ConcreteCreator;

impl Creator for ConcreteCreator {
    fn create(&self) -> Product {
        Product { name: 1 }
    }
}

pub fn client(creator: &dyn Creator) -> Product {
    Product { name: 0 }
}
'''

RUST_NO_CLASS_HIERARCHY = '''pub trait Creator {
    fn create(&self) -> Product;
}

pub struct Product {
    pub name: i32,
}

impl Creator for Product {
    fn create(&self) -> Product {
        Product { name: 1 }
    }
}

pub fn client(creator: &dyn Creator) -> Product {
    creator.create()
}
'''

CASES = {
    'go': ('go', GO, 'f.go'),
    'rust': ('rust', RUST, 'f.rs'),
}


def detect(language, source):
    graph = link_project([lower_source(source, language,
                                       'f.go' if language == 'go' else 'f.rs')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(CASES))
def test_client_calling_the_supplied_creation_slot_is_detected(language):
    lang, source, _ = CASES[language]
    matches = detect(lang, source)
    assert len(matches) == 1
    bindings = matches[0]['bindings']
    assert bindings['$contract'].endswith('/INTERFACE:Creator')
    assert bindings['$concrete'].endswith('/CLASS:ConcreteCreator')
    assert bindings['$product'].endswith('/CLASS:Product')
    assert bindings['$slot'] != bindings['$concrete']


def test_concrete_type_not_covering_the_whole_interface_is_rejected():
    """Go links only an exact method-set coverage."""
    assert not detect('go', GO_INCOMPLETE_INTERFACE)


def test_client_that_does_not_call_the_slot_is_rejected():
    assert not detect('go', GO_CLIENT_IGNORES_SLOT)


def test_client_calling_a_slot_of_another_contract_is_rejected():
    assert not detect('go', GO_OTHER_CONTRACT)


def test_rust_client_ignoring_the_slot_is_rejected():
    assert not detect('rust', RUST_CLIENT_IGNORES_SLOT)


def test_rust_trait_implemented_by_an_unrelated_type_is_accepted():
    """The contract is the trait, not a required class hierarchy."""
    matches = detect('rust', RUST_NO_CLASS_HIERARCHY)
    assert len(matches) == 1
    assert matches[0]['bindings']['$concrete'].endswith('/CLASS:Product')


def test_variant_is_ready_for_both_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'factory-method')
    row = next(v for v in rule.variants if v['id'] == 'contract-slot')
    assert row['languages'] == ['go', 'rust']
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'TARGET' in row['query'] and 'OVERRIDES' in row['query']
