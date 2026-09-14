"""Rust ownership wrappers denote their payload for slot typing.

``Box<Expr>``, ``Rc<Expr>`` and ``Arc<Expr>`` all hold an ``Expr``, so the field is
typed by that declaration. ``normalized_type`` already strips ``&``/``*`` but knows
no language, and ``TYPE_HEAD`` keeps the *head* of a generic (which is what resolves
``OnceLock<Service>`` to ``OnceLock``) -- for a smart pointer the head is the wrapper
and the payload is the declaration, so the unwrapped spelling wins. The unwrap is
guarded on the entity's language, so another language's own ``Box<T>`` type is
untouched.
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def graph(source):
    lowered = link_project([lower_source(source, 'rust', 'a.rs')])
    assert not lowered.diagnostics, lowered.diagnostics
    return lowered


def types(lowered):
    names = {key: entity.name for key, entity in lowered.entities.items()}
    return {(names[f.subject], names.get(f.object, f.object))
            for f in lowered.facts if f.relation == 'TYPE'}


@pytest.mark.parametrize('wrapper', ['Box', 'Rc', 'Arc'])
def test_smart_pointer_field_is_typed_by_its_payload(wrapper):
    lowered = graph(f'struct Expr {{ left: {wrapper}<Expr>, right: {wrapper}<Expr> }}\n')
    assert types(lowered) == {('left', 'Expr'), ('right', 'Expr')}
    for name in ('left', 'right'):
        slot = next(e for e in lowered.entities.values() if e.kind == 'STORAGE' and e.name == name)
        assert slot.attrs['type'] == 'Expr'
        assert slot.attrs['native_type'] == f'{wrapper}<Expr>'


def test_a_boxed_trait_object_is_typed_by_the_trait():
    lowered = graph('trait Node { fn size(&self) -> i32; }\n'
                    'struct Holder { item: Box<dyn Node> }\n')
    assert types(lowered) == {('item', 'Node')}


def test_a_collection_payload_is_not_a_smart_pointer():
    """``Vec<Expr>`` publishes an element type, not a slot type: the wrapper is not
    ownership of a single value."""
    lowered = graph('struct Expr { value: i32 }\nstruct Bag { items: Vec<Expr> }\n')
    assert types(lowered) == set()
    names = {key: entity.name for key, entity in lowered.entities.items()}
    elements = {(names[f.subject], names[f.object])
                for f in lowered.facts if f.relation == 'ELEMENT_TYPE'}
    assert ('items', 'Expr') in elements


def test_a_cell_slot_still_resolves_through_its_wrapper_head():
    """``OnceLock<Service>`` is still resolved through its head, so the existing
    wrapper-as-cell reading is not disturbed: the slot is the cell, not the payload."""
    lowered = graph('struct Service { value: i32 }\n'
                    'struct OnceLock { inner: i32 }\n'
                    'static INSTANCE: OnceLock<Service> = OnceLock::new();\n')
    assert ('INSTANCE', 'OnceLock') in types(lowered)
    assert ('INSTANCE', 'Service') not in types(lowered)
