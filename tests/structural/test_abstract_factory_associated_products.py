"""Abstract Factory ``associated-products``: two Rust families over one trait.

The variant is a published rule, so the test goes through the registry name
``abstract-factory#associated-products``.

The contract is expressed through the products each slot actually returns. Rust
``type X = Y`` declarations are not modelled, so the query deliberately does not
claim to have substituted an associated type.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'abstract-factory#associated-products'

FAMILIES = '''pub trait Factory {
    type Reader;
    type Writer;
    fn reader(&self) -> Self::Reader;
    fn writer(&self) -> Self::Writer;
}

pub struct FileReader;
pub struct FileWriter;
pub struct FileFactory;

impl Factory for FileFactory {
    type Reader = FileReader;
    type Writer = FileWriter;
    fn reader(&self) -> Self::Reader { FileReader }
    fn writer(&self) -> Self::Writer { FileWriter }
}

pub struct MemoryReader;
pub struct MemoryWriter;
pub struct MemoryFactory;

impl Factory for MemoryFactory {
    type Reader = MemoryReader;
    type Writer = MemoryWriter;
    fn reader(&self) -> Self::Reader { MemoryReader }
    fn writer(&self) -> Self::Writer { MemoryWriter }
}
'''

RENAMED = (FAMILIES.replace('Factory', 'Assembler').replace('FileReader', 'DiskSource')
           .replace('FileWriter', 'DiskSink').replace('MemoryReader', 'RamSource')
           .replace('MemoryWriter', 'RamSink').replace('FileFactory', 'DiskAssembler')
           .replace('MemoryFactory', 'RamAssembler'))

SHARED_ACROSS_FAMILIES = FAMILIES.replace('fn writer(&self) -> Self::Writer { MemoryWriter }',
                                          'fn writer(&self) -> Self::Writer { FileWriter }')

COLLAPSED_WITHIN_FAMILY = FAMILIES.replace('fn writer(&self) -> Self::Writer { FileWriter }',
                                           'fn writer(&self) -> Self::Writer { FileReader }')

ONE_FAMILY = FAMILIES.split('pub struct MemoryReader;')[0]

DECOY_TRAIT = '''pub trait Factory {
    fn reader(&self) -> i32;
    fn writer(&self) -> i32;
}
pub trait Decoy {
    fn reader(&self) -> i32;
    fn writer(&self) -> i32;
}
pub struct FileReader;
pub struct FileWriter;
pub struct FileFactory;
impl Factory for FileFactory {
    fn reader(&self) -> i32 { FileReader; 0 }
    fn writer(&self) -> i32 { FileWriter; 0 }
}
pub struct MemoryFactory;
impl Decoy for MemoryFactory {
    fn reader(&self) -> i32 { 1 }
    fn writer(&self) -> i32 { 2 }
}
'''

SINGLE_SLOT = '''pub trait Factory {
    fn reader(&self) -> i32;
}
pub struct FileReader;
pub struct FileFactory;
impl Factory for FileFactory {
    fn reader(&self) -> i32 { FileReader; 0 }
}
pub struct MemoryReader;
pub struct MemoryFactory;
impl Factory for MemoryFactory {
    fn reader(&self) -> i32 { MemoryReader; 0 }
}
'''


def detect(source):
    graph = link_project([lower_source(source, 'rust', 'factory.rs')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


def test_two_trait_families_with_distinct_products_are_detected():
    matches = detect(FAMILIES)
    assert len(matches) == 2
    assert {m['bindings']['$unit'].rsplit('/', 1)[-1] for m in matches} == {'CLASS:FileFactory',
                                                                           'CLASS:MemoryFactory'}
    for match in matches:
        assert match['bindings']['$contract'].endswith('/INTERFACE:Factory')


def test_renamed_trait_and_products_preserve_detection():
    matches = detect(RENAMED)
    assert len(matches) == 2
    assert {m['bindings']['$contract'].rsplit('/', 1)[-1] for m in matches} == {'INTERFACE:Assembler'}


def test_product_shared_across_families_is_rejected():
    """Two factories must not resolve the same slot to one product."""
    assert not detect(SHARED_ACROSS_FAMILIES)


def test_family_collapsing_both_slots_onto_one_product_is_rejected():
    """Each family must keep its two creation slots distinct."""
    assert not detect(COLLAPSED_WITHIN_FAMILY)


def test_single_family_is_rejected():
    assert not detect(ONE_FAMILY)


def test_type_implementing_another_trait_is_not_a_family():
    assert not detect(DECOY_TRAIT)


def test_trait_with_a_single_creation_slot_is_rejected():
    assert not detect(SINGLE_SLOT)


def test_variant_is_ready_for_its_single_declared_language():
    rule = next(r for r in _load_catalog() if r.id == 'abstract-factory')
    row = next(v for v in rule.variants if v['id'] == 'associated-products')
    assert row['languages'] == ['rust']
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'OVERRIDES' in row['query'] and 'SUBTYPE_OF' in row['query']
