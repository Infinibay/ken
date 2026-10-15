import pytest
from ken.retrieval.model import EntityKey, Span
from ken.structural.frontend import lower_source


def test_resolved_calls_use_canonical_source_and_target_headers():
    from source_context import collect_call_edges
    source = b'def helper(value):\n    return value\n\ndef apply(value):\n    return helper(value)\n'
    helper = EntityKey('toy.py', 'function', 'helper')
    apply = EntityKey('toy.py', 'function', 'apply')
    edges, diagnostics = collect_call_edges(lower_source(source, 'python', 'toy.py'),
        {helper: (Span(1, 2),), apply: (Span(4, 5),)})
    assert len(edges) == 1
    assert (edges[0].caller, edges[0].callee) == (apply, helper)
    assert edges[0].call_span == Span(5, 5)
    assert edges[0].target_line == 1
    assert diagnostics['unmapped_target'] == 0


def test_unresolved_external_spelling_does_not_guess_a_named_sibling():
    from source_context import collect_call_edges
    source = b'def helper(value):\n    return value\n\ndef apply(external, value):\n    return external.helper(value)\n'
    helper = EntityKey('toy.py', 'function', 'helper')
    apply = EntityKey('toy.py', 'function', 'apply')
    edges, diagnostics = collect_call_edges(lower_source(source, 'python', 'toy.py'),
        {helper: (Span(1, 2),), apply: (Span(4, 5),)})
    assert edges == ()
    assert diagnostics['unresolved_call'] == 1


def test_nested_calls_belong_to_the_inner_callable():
    from source_context import collect_call_edges
    source = b'def helper(x):\n    return x\n\ndef outer(x):\n    def child(y):\n        return helper(y)\n    return child(x)\n'
    helper = EntityKey('toy.py', 'function', 'helper')
    outer = EntityKey('toy.py', 'function', 'outer')
    child = EntityKey('toy.py', 'function', 'outer.child', 'outer')
    edges, _ = collect_call_edges(lower_source(source, 'python', 'toy.py'),
        {helper: (Span(1, 2),), outer: (Span(4, 4), Span(7, 7)), child: (Span(5, 6),)})
    assert {(e.caller, e.callee) for e in edges} == {(child, helper), (outer, child)}


def test_parent_context_requires_canonical_parent_and_unique_containment():
    from source_context import enclosing_edges
    a = EntityKey('toy.py', 'function', 'outer')
    b = EntityKey('toy.py', 'function', 'outer.child', 'outer')
    c = EntityKey('toy.py', 'function', 'sibling')
    assert enclosing_edges({a: Span(1, 10), b: Span(3, 5), c: Span(12, 16)}) == ((a, b),)
    other = EntityKey('toy.py', 'function', 'outer', definition_ordinal=1)
    assert enclosing_edges({a: Span(1, 10), other: Span(1, 10), b: Span(3, 5)}) == ()


def test_source_context_rejects_overlapping_ownership():
    from source_context import collect_call_edges
    a = EntityKey('toy.py', 'function', 'helper')
    b = EntityKey('toy.py', 'module', None)
    with pytest.raises(ValueError, match='overlap'):
        collect_call_edges(lower_source(b'def helper():\n    return helper()\n', 'python', 'toy.py'),
            {a: (Span(1, 2),), b: (Span(2, 2),)})


def test_java_overloaded_declarations_remain_unknown_without_overload_resolution():
    from source_context import collect_call_edges
    source = b'class Example {\n  int helper(int value) { return value; }\n  String helper(String value) { return value; }\n  int apply(int value) { return helper(value); }\n}\n'
    a = EntityKey('toy.java', 'method', 'Example.helper', 'Example')
    b = EntityKey('toy.java', 'method', 'Example.helper', 'Example', 1)
    caller = EntityKey('toy.java', 'method', 'Example.apply', 'Example')
    edges, diagnostics = collect_call_edges(lower_source(source, 'java', 'toy.java'),
        {a: (Span(2, 2),), b: (Span(3, 3),), caller: (Span(4, 4),)})
    assert edges == ()
    assert diagnostics['ambiguous_definition'] == 1


def test_reassigned_python_callable_binding_is_not_a_resolved_target():
    from source_context import collect_call_edges
    source = b'def helper(x):\n    return x\n\nhelper = external\n\ndef apply(x):\n    return helper(x)\n'
    a = EntityKey('toy.py', 'function', 'helper')
    caller = EntityKey('toy.py', 'function', 'apply')
    module = EntityKey('toy.py', 'module', None)
    edges, diagnostics = collect_call_edges(lower_source(source, 'python', 'toy.py'),
        {a: (Span(1, 2),), module: (Span(4, 4),), caller: (Span(6, 7),)})
    assert edges == ()
    assert diagnostics['target_written'] == 1


def test_redefined_class_header_never_selects_the_first_ordinal():
    from source_context import collect_call_edges
    source = b'class C:\n    pass\n\nclass C:\n    pass\n\ndef apply():\n    return C()\n'
    a = EntityKey('toy.py', 'class', 'C')
    b = EntityKey('toy.py', 'class', 'C', definition_ordinal=1)
    caller = EntityKey('toy.py', 'function', 'apply')
    edges, diagnostics = collect_call_edges(lower_source(source, 'python', 'toy.py'),
        {a: (Span(1, 2),), b: (Span(4, 5),), caller: (Span(7, 8),)})
    assert edges == ()
    assert diagnostics['ambiguous_definition'] == 1
