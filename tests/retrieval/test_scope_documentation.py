from ken.parsers.rust import parse_rust_file
from ken.retrieval.passages import extract_passages
import pytest


def test_rust_scope_keeps_full_documentation_across_interleaved_attributes():
    source = b'''impl Envelope {
    /// Transfer the pointer without allocation.
    ///
    /// The original backtrace remains available.
    #[cfg_attr(feature = "nightly", doc = "example wrapper")]
    /// This final paragraph belongs to the same method.
    #[must_use]
    pub fn into_box(self) -> Box<dyn Error> { move_pointer(self) }
}
'''
    parsed = parse_rust_file(source, 'envelope.rs')
    scope = next(s for s in parsed.scopes if s.symbol.qualname == 'Envelope.into_box')
    assert scope.documentation == (
        'Transfer the pointer without allocation.\n\n'
        'The original backtrace remains available.\n'
        'This final paragraph belongs to the same method.'
    )
    assert 'example wrapper' not in scope.documentation
    assert scope.symbol.line_start == 8
    passages = [p for p in extract_passages(source, parsed, path='envelope.rs', language='rust')
                if p.entity.qualname == 'Envelope.into_box']
    assert passages
    assert all(p.fields['documentation'] == scope.documentation for p in passages)
    assert all('move_pointer' in p.fields['body'] for p in passages)
    assert all('Transfer the pointer' not in p.fields['body'] for p in passages)


def test_rust_documentation_does_not_cross_a_different_declaration():
    source = b'''/// First declaration only.
#[must_use]
pub fn first() -> bool { true }

#[inline]
pub fn second() -> bool { false }
'''
    scopes = {s.symbol.qualname: s for s in parse_rust_file(source, 'items.rs').scopes}
    assert scopes['first'].documentation == 'First declaration only.'
    assert scopes['second'].documentation is None


def test_block_documentation_is_available_after_rust_attributes():
    source = b'''/**
 * Reuse an existing buffer.
 * Its capacity is preserved.
 */
#[inline]
pub fn reuse(buffer: Buffer) -> Buffer { buffer }
'''
    parsed = parse_rust_file(source, 'reuse.rs')
    assert parsed.scopes[0].documentation == 'Reuse an existing buffer.\nIts capacity is preserved.'


@pytest.mark.parametrize('comment', ['//! Module documentation.', '/*! Module documentation. */'])
def test_rust_inner_documentation_keeps_its_enclosing_owner(comment):
    source = (comment+'\n#[inline]\npub fn first() {}\n').encode()
    parsed = parse_rust_file(source, 'module.rs')
    assert parsed.scopes[0].documentation is None


def test_trailing_comment_does_not_become_documentation_of_a_later_item():
    source = b'''pub fn first() {} // This describes first.
#[inline]
pub fn second() {}
'''
    parsed = parse_rust_file(source, 'trailing.rs')
    assert all(scope.documentation is None for scope in parsed.scopes)


def test_rust_outer_block_documentation_can_precede_an_item_on_the_same_line():
    source = b'/** Own documentation. */ pub fn first() {}\n'
    parsed = parse_rust_file(source, 'inline.rs')
    assert parsed.scopes[0].documentation == 'Own documentation.'


@pytest.mark.parametrize('comment', ['/// Next item documentation.', '/** Next item documentation. */'])
def test_outer_documentation_after_previous_item_still_belongs_to_next_item(comment):
    source = ('pub fn first() {} '+comment+'\n#[inline]\npub fn second() {}\n').encode()
    scopes = {s.symbol.qualname: s for s in parse_rust_file(source, 'outer.rs').scopes}
    assert scopes['first'].documentation is None
    assert scopes['second'].documentation == 'Next item documentation.'


def test_cpp_scopes_preserve_full_template_contract_and_all_owner_kinds():
    from ken.parsers.cpp import parse_cpp_file
    source = b"""namespace sample {
class Reader {
public:
  /** Return the supplied value.
   * Preserve its original type without allocation.
   */
  template<class T>
  T read(
      T value
  ) const {
    return value;
  }
};
enum class Mode { Single, Many };
using Size = unsigned long;
}
"""
    parsed = parse_cpp_file(source, "reader.hpp")
    scopes = {scope.symbol.qualname: scope for scope in parsed.scopes}
    assert set(scopes) == {symbol.qualname for symbol in parsed.symbols}
    scope = scopes["sample.Reader.read"]
    assert scope.documentation == "Return the supplied value.\nPreserve its original type without allocation."
    assert scope.signature.strip() == "template<class T>\n  T read(\n      T value\n  ) const"
    assert scope.owner == "sample.Reader"
    assert scope.implementation_start_line == 11
    assert scope.statements == [(11, 11)]
    passages = [passage for passage in extract_passages(source, parsed, path="reader.hpp", language="cpp")
                if passage.entity.qualname == "sample.Reader.read"]
    assert passages
    assert all(p.fields["documentation"] == scope.documentation for p in passages)
    assert all("return value" not in p.fields["signature"] for p in passages)
    assert {scope.symbol.kind for scope in parsed.scopes} >= {"class", "method", "enum", "typedef"}
