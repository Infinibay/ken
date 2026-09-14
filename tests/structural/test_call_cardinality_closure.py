"""The claim behind ``complete:<callable>:HAS_CALL`` (IR 1.61).

KenQL accepts exact cardinality (``count distinct $x = 1 { … }``) and scoped absence
(``not exists { … } within callable($x)``) only when the block is *closed*, and closure
requires a ``complete:<subject>:<relation>`` capability. Declaring one for ``HAS_CALL``
is a claim about the **language**, not about the graph: every call form the language
offers is classified, so a callable's calls are enumerated rather than sampled.

This file makes that claim testable. Each entry is one call form, in one language, with
exactly one call in it, and the expected syntactic callee name. Adding a call form to a
grammar -- or a grammar renaming a node -- fails here *before* the completeness claim
becomes a lie, which is the only thing that makes the claim safe to publish.

Rust macro invocations (``println!``) are deliberately absent: a macro invocation is not
a call in the grammar, and the IR models no expansion.
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import query_graph
from ken.structural.semantic import link_project

EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}

# (language, label, source, expected syntactic callee name)
CASES = [
    ('python', 'direct', 'def f():\n    g()\n', 'g'),
    ('python', 'method', 'def f():\n    obj.m()\n', 'm'),
    ('python', 'constructor', 'def f():\n    C()\n', 'C'),
    ('python', 'await', 'async def f():\n    await g()\n', 'g'),

    ('javascript', 'direct', 'function f() { g(); }\n', 'g'),
    ('javascript', 'method', 'function f() { obj.m(); }\n', 'm'),
    ('javascript', 'constructor', 'function f() { new C(); }\n', 'C'),
    ('javascript', 'optional-call', 'function f() { g?.(); }\n', 'g'),
    ('javascript', 'tagged-template', 'function f() { tag`x`; }\n', 'tag'),

    ('typescript', 'direct', 'function f(): void { g(); }\n', 'g'),
    ('typescript', 'method', 'function f(): void { obj.m(); }\n', 'm'),
    ('typescript', 'constructor', 'function f(): void { new C(); }\n', 'C'),
    ('typescript', 'optional-call', 'function f(): void { g?.(); }\n', 'g'),

    ('java', 'method', 'class F { void f() { obj.m(); } }\n', 'm'),
    ('java', 'constructor', 'class F { void f() { C c = new C(); } }\n', 'C'),
    ('java', 'super-delegation', 'class F { F() { super(); } }\n', 'super'),
    ('java', 'this-delegation', 'class F { F(int x) { this(); } }\n', 'this'),

    ('csharp', 'method', 'class F { void M() { obj.M2(); } }\n', 'M2'),
    ('csharp', 'constructor', 'class F { void M() { var c = new C(); } }\n', 'C'),
    ('csharp', 'base-delegation', 'class F { F() : base() { } }\n', 'base'),
    ('csharp', 'this-delegation', 'class F { F(int x) : this() { } }\n', 'this'),

    ('cpp', 'direct', 'void f() { g(); }\n', 'g'),
    ('cpp', 'method', 'void f() { obj.m(); }\n', 'm'),
    ('cpp', 'constructor', 'void f() { C* c = new C(); }\n', 'C'),
    ('cpp', 'functional-cast', 'void f() { C c = C(1); }\n', 'C'),

    ('go', 'direct', 'package p\n\nfunc f() { g() }\n', 'g'),
    ('go', 'method', 'package p\n\nfunc f() { obj.M() }\n', 'M'),
    ('go', 'composite-literal', 'package p\n\ntype C struct{ v int }\n\nfunc f() { _ = C{v: 1} }\n', 'C'),
    ('go', 'deferred', 'package p\n\nfunc f() { defer g() }\n', 'g'),
    ('go', 'goroutine', 'package p\n\nfunc f() { go g() }\n', 'g'),

    ('rust', 'direct', 'fn f() { g(); }\n', 'g'),
    ('rust', 'method', 'fn f() { obj.m(); }\n', 'm'),
    ('rust', 'struct-expression', 'struct C { v: i32 }\n\nfn f() { let c = C { v: 1 }; }\n', 'C'),
    ('rust', 'scoped-call', 'struct C;\n\nimpl C { fn new() -> C { C } }\n\nfn f() { let c = C::new(); }\n', 'C::new'),
]


@pytest.mark.parametrize('language,label,source,callee', CASES,
                         ids=[f'{c[0]}-{c[1]}' for c in CASES])
def test_every_call_form_is_classified_as_a_call(language, label, source, callee):
    graph = link_project([lower_source(source, language, f'form.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, (language, label, graph.diagnostics)
    calls = [e for e in graph.entities.values() if e.kind == 'CALL']
    assert len(calls) == 1, (language, label, [e.id for e in calls])
    owned = {f.object for f in graph.facts if f.relation == 'HAS_CALL'}
    assert calls[0].id in owned, (language, label, 'the call is not recorded by HAS_CALL')
    assert calls[0].attrs.get('name') == callee, (language, label, calls[0].attrs.get('name'))


@pytest.mark.parametrize('language,label,source,callee', CASES,
                         ids=[f'{c[0]}-{c[1]}' for c in CASES])
def test_the_owning_callable_publishes_call_completeness(language, label, source, callee):
    graph = link_project([lower_source(source, language, f'form.{EXTENSIONS[language]}')])
    view = query_graph(graph).ir
    owners = {f.subject for f in view.facts if f.relation == 'HAS_CALL'}
    assert owners, (language, label)
    for owner in owners:
        assert f'complete:{owner}:HAS_CALL' in view.capabilities, (language, label, owner)


def test_completeness_is_withheld_when_the_source_does_not_parse():
    """An erroneous parse records nothing trustworthy, so the claim is not made."""
    graph = link_project([lower_source('def f(:\n    g()\n', 'python', 'broken.py')])
    assert graph.diagnostics
    view = query_graph(graph).ir
    owners = {f.subject for f in view.facts if f.relation == 'HAS_CALL'}
    assert owners
    for owner in owners:
        assert f'complete:{owner}:HAS_CALL' not in view.capabilities, owner


def test_nested_closures_keep_their_own_calls():
    """Ownership is per innermost callable, so an outer count never sees inner calls."""
    source = '''def outer():
    def inner():
        g()
    return inner
'''
    graph = link_project([lower_source(source, 'python', 'nested.py')])
    owners = {f.subject for f in graph.facts if f.relation == 'HAS_CALL' and f.object}
    callables = {e.id for e in graph.entities.values() if e.kind == 'CALLABLE'}
    owned_callables = owners & callables
    assert len(owned_callables) == 1, owned_callables
    owner = owned_callables.pop()
    assert 'inner' in owner, owner
