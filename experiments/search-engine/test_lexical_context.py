"""Public usage contract: canonical identity plus faithful nested source context."""
from dataclasses import replace
import hashlib

import pytest

from ken.parsers.python import parse_python_file
from ken.retrieval.model import EntityKey, Span
from ken.retrieval.passages import extract_passages


def prepare(source, path='sample.py'):
    data = source.encode('utf-8')
    parsed = parse_python_file(data, path)
    passages = extract_passages(data, parsed, path=path, language='python')
    return data, passages


def build(data, passages, path='sample.py'):
    from lexical_context import build_lexical_contexts
    return build_lexical_contexts(data, passages, path=path, language='python',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())


def test_nested_source_is_context_with_its_own_identity_not_reassigned_to_parent():
    data, passages = prepare('''def outer(value):
    def child():
        return "nested implementation"
    return child

def sibling():
    return "unrelated"
''')
    before = tuple(passages)
    catalog = build(data, passages)
    outer = EntityKey('sample.py', 'function', 'outer')
    child = EntityKey('sample.py', 'function', 'outer.child', 'outer')
    context = catalog.contexts[outer]
    assert context.primary == outer
    assert context.source_hash == hashlib.sha256(data).hexdigest()
    assert context.generation == 'source7-test-generation'
    assert context.extent == Span(1, 4)
    assert context.text == data.decode().split('\n\n')[0]
    assert [(p.owner, p.span) for p in context.parts] == [
        (outer, Span(1, 1)), (child, Span(2, 3)), (outer, Span(4, 4))]
    assert [(s.native_kind, s.parent_index) for s in context.scopes] == [
        ('function_definition', None), ('function_definition', 0)]
    assert 'unrelated' not in context.text
    assert tuple(passages) == before
    assert all(p.entity == outer for p in passages if p.span.start_line in (1, 4))


def test_redefinitions_keep_definition_ordinals_and_never_include_siblings():
    data, passages = prepare('''def outer(flag):
    if flag:
        def item():
            return "first"
    else:
        def item():
            return "second"
    return item
''')
    catalog = build(data, passages)
    children = sorted((c for e, c in catalog.contexts.items() if e.qualname == 'outer.item'),
                      key=lambda c: c.primary.definition_ordinal)
    assert len(children) == 2
    assert 'second' not in children[0].text
    assert 'first' not in children[1].text
    assert children[0].primary.definition_ordinal == 0
    assert children[1].primary.definition_ordinal == 1
    assert {p.owner.definition_ordinal for p in catalog.contexts[
        EntityKey('sample.py', 'function', 'outer')].parts if p.owner and p.owner.qualname == 'outer.item'} == {0, 1}


def test_dead_helpers_and_rebinding_remain_lexical_source_without_execution_claims():
    data, passages = prepare('''def outer(external):
    if False:
        def unused():
            return "never run"
    def value():
        return "local"
    value = external
    return value
''')
    catalog = build(data, passages)
    context = catalog.contexts[EntityKey('sample.py', 'function', 'outer')]
    assert 'never run' in context.text and 'value = external' in context.text
    assert context.relation == 'lexically_contains'
    assert not hasattr(context, 'callee') and not hasattr(context, 'executed')


def test_same_line_siblings_fail_closed_rather_than_showing_unrelated_source():
    from ken.parsers.javascript import parse_js_file
    from lexical_context import build_lexical_contexts
    data = b'const one = () => 1; const two = () => 2;\n'
    passages = extract_passages(data, parse_js_file(data, 'sample.js'), path='sample.js', language='javascript')
    catalog = build_lexical_contexts(data, passages, path='sample.js', language='javascript',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    assert not catalog.contexts
    assert any(d.reason == 'ambiguous_or_partial_line_scope' for d in catalog.diagnostics)


def test_utf8_byte_offsets_and_crlf_source_are_preserved():
    data, passages = prepare('def outer():\r\n    text = "ñ 🐈"\r\n    def child():\r\n        return text\r\n    return child\r\n')
    context = build(data, passages).contexts[EntityKey('sample.py', 'function', 'outer')]
    for part in context.parts:
        assert part.text == data[part.start_byte:part.end_byte].decode('utf-8')
    assert b''.join(data[p.start_byte:p.end_byte] for p in context.parts) == data[:context.end_byte]
    assert context.text == data[:context.end_byte].decode('utf-8')


@pytest.mark.parametrize('change', ['hash', 'path', 'identity', 'missing', 'generation'])
def test_stale_or_incomplete_canonical_snapshot_is_rejected(change):
    from lexical_context import build_lexical_contexts
    data, passages = prepare('def outer():\n    def child():\n        return 1\n    return child\n')
    generation = 'source7-test-generation'
    digest = hashlib.sha256(data).hexdigest()
    if change == 'hash':
        passages = [replace(p, source_hash='0' * 64) for p in passages]
    elif change == 'path':
        passages = [replace(p, entity=replace(p.entity, path='elsewhere.py')) for p in passages]
    elif change == 'identity':
        passages = [replace(p, entity=replace(p.entity, qualname='wrong')) for p in passages]
    elif change == 'missing':
        passages = passages[:-1]
    elif change == 'generation':
        generation = ''
    with pytest.raises(ValueError):
        build_lexical_contexts(data, passages, path='sample.py', language='python',
            generation=generation, expected_source_hash=digest)


def test_syntax_errors_are_diagnostic_and_do_not_authorize_context():
    data, passages = prepare('def broken(:\n    return 1\n')
    catalog = build(data, passages)
    assert not catalog.contexts
    assert any(d.reason == 'syntax_error' for d in catalog.diagnostics)


def test_class_members_do_not_become_the_context_of_other_methods():
    data, passages = prepare('''class Store:
    def put(self):
        class Local:
            def run(self):
                return "local method"
        return Local

    def erase(self):
        return "other method"
''')
    catalog = build(data, passages)
    context = catalog.contexts[EntityKey('sample.py', 'method', 'Store.put', 'Store')]
    assert 'local method' in context.text and 'other method' not in context.text
    assert 'class_definition' in {s.native_kind for s in context.scopes}
    assert all(e.kind != 'module' and e.kind != 'class' for e in catalog.contexts)


def test_ecmascript_bound_closure_keeps_carrier_and_nested_owners():
    from ken.parsers.typescript import parse_ts_file
    from lexical_context import build_lexical_contexts
    data = b'''class Factory {
  make(value: number) {
    const parse = () => {
      return Promise.resolve(value);
    };
    return parse;
  }
  sibling() {
    return "unrelated";
  }
}
'''
    passages = extract_passages(data, parse_ts_file(data, 'sample.ts'), path='sample.ts', language='typescript')
    catalog = build_lexical_contexts(data, passages, path='sample.ts', language='typescript',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    context = catalog.contexts[EntityKey('sample.ts', 'method', 'Factory.make', 'Factory')]
    assert 'Promise.resolve(value)' in context.text and 'unrelated' not in context.text
    assert any(p.owner and p.owner.qualname == 'Factory.make.parse' for p in context.parts)
    child = catalog.contexts[EntityKey('sample.ts', 'function', 'Factory.make.parse', 'Factory.make')]
    assert child.text.lstrip().startswith('const parse =')
    assert child.scopes[0].native_kind == 'arrow_function'


def test_source_language_without_structural_frontend_is_a_diagnostic():
    from ken.parsers.c import parse_c_file
    from lexical_context import build_lexical_contexts
    data = b'int f(void) { return 1; }\n'
    passages = extract_passages(data, parse_c_file(data, 'sample.c'), path='sample.c', language='c')
    catalog = build_lexical_contexts(data, passages, path='sample.c', language='c',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    assert not catalog.contexts
    assert any(d.reason == 'structural_grammar_unavailable' for d in catalog.diagnostics)


@pytest.mark.parametrize('data', [
    b'const one = () => 1, unrelated = eraseAll();\n',
    b'const one = () => {\n  return 1;\n}, unrelated = eraseAll();\n',
])
def test_a_declaration_with_other_initializers_cannot_authorize_sibling_source(data):
    from ken.parsers.javascript import parse_js_file
    from lexical_context import build_lexical_contexts
    passages = extract_passages(data, parse_js_file(data, 'sample.js'), path='sample.js', language='javascript')
    catalog = build_lexical_contexts(data, passages, path='sample.js', language='javascript',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    assert not catalog.contexts
    assert any(d.reason == 'ambiguous_or_partial_line_scope' for d in catalog.diagnostics)


@pytest.mark.parametrize('pattern', [
    '{value = eraseAll()}', '{[eraseAll()]: value}', '[value = eraseAll()]',
])
def test_destructuring_initializers_are_not_callable_context(pattern):
    from ken.parsers.javascript import parse_js_file
    from lexical_context import build_lexical_contexts
    data = f'const {pattern} = () => 1;\n'.encode()
    passages = extract_passages(data, parse_js_file(data, 'sample.js'), path='sample.js', language='javascript')
    catalog = build_lexical_contexts(data, passages, path='sample.js', language='javascript',
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    assert not catalog.contexts
    assert any(d.reason == 'ambiguous_or_partial_line_scope' for d in catalog.diagnostics)


@pytest.mark.parametrize(('path', 'language', 'data', 'qualname'), [
    ('sample.rs', 'rust', b'fn outer() {\n    let child = || { 1 };\n    child\n}\n', 'outer'),
    ('sample.go', 'go', b'package sample\nfunc outer() func() int {\n    return func() int { return 1 }\n}\n', 'outer'),
    ('Sample.java', 'java', b'class Sample {\n  Runnable outer() {\n    return () -> { run(); };\n  }\n}\n', 'Sample.outer'),
])
def test_other_existing_grammars_preserve_anonymous_nested_syntax(path, language, data, qualname):
    from pathlib import Path
    from ken.parsers import detect_language
    from lexical_context import build_lexical_contexts
    detected = detect_language(Path(path))
    passages = extract_passages(data, detected[1](data, path), path=path, language=language)
    catalog = build_lexical_contexts(data, passages, path=path, language=language,
        generation='source7-test-generation', expected_source_hash=hashlib.sha256(data).hexdigest())
    context = next(c for e, c in catalog.contexts.items() if e.qualname == qualname)
    assert len(context.scopes) == 2
    assert context.scopes[0].parent_index is None
    assert context.scopes[1].parent_index == 0
    assert context.text.encode() == data[context.start_byte:context.end_byte]
