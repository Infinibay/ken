from ken.retrieval.model import EntityKey, Span
from ken.structural.frontend import lower_source
import pytest


def test_guard_relations_keep_the_actual_condition_and_each_branch():
    from source_relations import collect_relations

    source = b'''def convert(value, converter):
    if value is None:
        return None
    else:
        return converter(value)
'''
    owner = EntityKey('convert.py', 'function', 'convert')
    rows = collect_relations(source, lower_source(source, 'python', 'convert.py'), {owner: (Span(1, 5),)})[owner]
    guards = [r for r in rows if r.kind == 'guarded_effects']
    assert any('when value is None' in r.text and 'return None' in r.text for r in guards)
    assert any('otherwise value is None' in r.text and 'converter(value)' in r.text for r in guards)
    assert all(r.spans[0] == Span(2, 2) for r in guards)
    assert any(r.kind == 'value_relations' and 'input parameters' in r.text for r in rows)


def test_a_parent_condition_never_becomes_a_nested_callable_guard():
    from source_relations import collect_relations

    source = b'''def outer(flag):
    if flag:
        def child():
            return "nested"
        return child
'''
    outer = EntityKey('scope.py', 'function', 'outer')
    child = EntityKey('scope.py', 'function', 'outer.child', 'outer')
    rows = collect_relations(source, lower_source(source, 'python', 'scope.py'),
        {outer: (Span(1, 2), Span(5, 5)), child: (Span(3, 4),)})
    assert not any(r.kind == 'guarded_effects' for r in rows[child])
    assert not any('"nested"' in r.text for r in rows[outer])
    assert any('when flag' in r.text and 'return child' in r.text for r in rows[outer])


def test_call_relations_keep_receiver_arguments_and_assertion_spelling():
    from source_relations import collect_relations

    source = b'''function check(value) {
  const result = cache.read(value);
  assert.equal(result, value);
  return result;
}
'''
    owner = EntityKey('check.js', 'function', 'check')
    rows = collect_relations(source, lower_source(source, 'javascript', 'check.js'), {owner: (Span(1, 5),)})[owner]
    assert any(r.kind == 'call_relations' and 'cache.read(value)' in r.text for r in rows)
    assert any(r.kind == 'assertions' and 'assert.equal(result, value)' in r.text for r in rows)
    assert any(r.kind == 'value_relations' and 'result = cache.read(value)' in r.text for r in rows)


@pytest.mark.parametrize(('language', 'source'), [
    ('rust', 'fn check(value: i32) -> i32 { if value == 0 { return 1; } return value; }'),
    ('go', 'package sample\nfunc check(value int) int { if value == 0 { return 1 }; return value }'),
    ('java', 'class Check { int check(int value) { if (value == 0) { return 1; } return value; } }'),
    ('typescript', 'function check(value: number) { if (value === 0) { return 1; } return value; }'),
])
def test_existing_grammar_roles_preserve_conditions_across_languages(language, source):
    from source_relations import collect_relations

    data = source.encode()
    owner = EntityKey('sample', 'function', 'check')
    rows = collect_relations(data, lower_source(data, language, 'sample'),
        {owner: (Span(1, len(source.splitlines())),)})[owner]
    assert any(r.kind == 'conditions' and 'value' in r.text for r in rows)
    assert any(r.kind == 'guarded_effects' and 'when' in r.text and 'return 1' in r.text for r in rows)


def test_source_relations_reject_overlapping_ownership():
    from source_relations import collect_relations

    source = b'def check():\n    return 1\n'
    a, b = EntityKey('sample.py', 'function', 'check'), EntityKey('sample.py', 'module', None)
    with pytest.raises(ValueError, match='overlap'):
        collect_relations(source, lower_source(source, 'python', 'sample.py'),
            {a: (Span(1, 2),), b: (Span(2, 2),)})


def test_ruby_unless_preserves_the_inverted_syntactic_condition():
    from source_relations import collect_relations

    source = b'def check(ready)\n  unless ready\n    publish()\n  else\n    cancel()\n  end\nend\n'
    owner = EntityKey('check.rb', 'method', 'check')
    rows = collect_relations(source, lower_source(source, 'ruby', 'check.rb'), {owner: (Span(1, 7),)})[owner]
    assert any(r.kind == 'guarded_effects' and 'otherwise ready' in r.text and 'publish()' in r.text for r in rows)
    assert any(r.kind == 'guarded_effects' and 'when ready' in r.text and 'cancel()' in r.text for r in rows)
