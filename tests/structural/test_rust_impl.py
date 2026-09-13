"""Nominal ownership must survive lifetime, type and const arguments in impls."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


@pytest.mark.parametrize('declaration,implementation', [
 ('struct Store { value: i32 }', 'impl Store'),
 ("struct Store<'a> { value: &'a str }", "impl<'a> Store<'a>"),
 ('struct Store<T> { value: T }', 'impl<T> Store<T>'),
 ('struct Store<const N: usize> { value: [u8; N] }', 'impl<const N: usize> Store<N>'),
])
@pytest.mark.parametrize('impl_first', [False, True])
def test_rust_impl_members_keep_nominal_owner(declaration, implementation, impl_first):
    block = implementation + ' { fn touch(&mut self) { inspect(&self.value); } }'
    source = block + declaration if impl_first else declaration + block
    graph = link_project([lower_source(source, 'rust', 'store.rs')])
    assert not graph.diagnostics
    owner = next(e.id for e in graph.entities.values() if e.kind == 'CLASS' and e.name == 'Store')
    method = next(e.id for e in graph.entities.values() if e.kind == 'CALLABLE' and e.name == 'touch')
    assert any(f.subject == owner and f.relation == 'HAS_METHOD' and f.object == method for f in graph.facts)
    assert any(f.subject == method and f.relation == 'IN_TYPE' and f.object == owner for f in graph.facts)
    storage = next(f.object for f in graph.facts if f.subject == owner and f.relation == 'HAS_FIELD' and graph.entities[f.object].name == 'value')
    assert any(f.subject == method and f.relation == 'READS' and f.object == storage for f in graph.facts)


def test_qualified_impl_does_not_attach_to_unrelated_local_type():
    source = 'struct Store<T> { value: T } impl external::Store<u8> { fn touch(&self) {} }'
    graph = link_project([lower_source(source, 'rust', 'store.rs')])
    assert not graph.diagnostics
    assert not any(f.relation == 'HAS_METHOD' for f in graph.facts)
