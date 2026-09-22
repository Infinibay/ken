"""Decorator ``callable-wrapper``: a closure wrapping a callable it captured.

The variant is a published rule, so the test goes through the registry name
``decorator#callable-wrapper``.

The invocation of the captured callable is accepted in two shapes, because the
graph records them differently and both mean "call the callable": a direct call
(``inner(value)``, ``CALLEE_VALUE``) and a method on the callable
(``inner.applyAsInt(value)``, ``RECEIVER``), which is how Java invokes a
functional interface.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'decorator#callable-wrapper'

SOURCES = {
    'python': ('''def traced(inner):
    def run(value):
        print("before")
        result = inner(value)
        print("after")
        return result
    return run
''', 'd.py'),
    'javascript': ('''function traced(inner) {
  return function run(value) {
    console.log("before");
    const result = inner(value);
    console.log("after");
    return result;
  };
}
''', 'd.js'),
    'typescript': ('''function traced(inner: (v: number) => number): (v: number) => number {
  return function run(value: number): number {
    console.log("before");
    const result = inner(value);
    console.log("after");
    return result;
  };
}
''', 'd.ts'),
    'java': ('''import java.util.function.IntUnaryOperator;
class Traced {
  static IntUnaryOperator traced(IntUnaryOperator inner) {
    return value -> {
      System.out.println("before");
      int result = inner.applyAsInt(value);
      System.out.println("after");
      return result;
    };
  }
}
''', 'T.java'),
    'csharp': ('''using System;
class Traced {
  static Func<int,int> Traced(Func<int,int> inner) {
    return value => {
      Console.WriteLine("before");
      var result = inner(value);
      Console.WriteLine("after");
      return result;
    };
  }
}
''', 'T.cs'),
    'cpp': ('''#include <functional>
#include <cstdio>
std::function<int(int)> traced(std::function<int(int)> inner) {
  return [inner](int value) {
    std::puts("before");
    int result = inner(value);
    return result;
  };
}
''', 't.cpp'),
    'go': ('''package decorator

func Traced(inner func(int) int) func(int) int {
	return func(value int) int {
		println("before")
		result := inner(value)
		println("after")
		return result
	}
}
''', 'd.go'),
    'rust': ('''pub fn traced<F: Fn(i32) -> i32>(inner: F) -> impl Fn(i32) -> i32 {
    move |value: i32| {
        println!("before");
        let result = inner(value);
        println!("after");
        result
    }
}
''', 'd.rs'),
}

RENAMED_PYTHON = '''def wrap(operation):
    def wrapped(item):
        print("trace")
        outcome = operation(item)
        return outcome
    return wrapped
'''

RETURNS_INNER_DIRECTLY = '''def traced(inner):
    return inner
'''

NEVER_INVOKES = '''def traced(inner):
    def run(value):
        print("before")
        return value
    return run
'''

INVOKES_ANOTHER_CALLABLE = '''def other(value):
    return value

def traced(inner):
    def run(value):
        print("before")
        result = other(value)
        return result
    return run
'''

DROPS_THE_ARGUMENT = '''def traced(inner):
    def run(value):
        print("before")
        result = inner(0)
        return result
    return run
'''

NO_PARAMETER_TO_CAPTURE = '''def helper(value):
    return value

def traced():
    def run(value):
        return helper(value)
    return run
'''


def detect(language, source, path):
    graph = link_project([lower_source(source, language, path)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
def test_closure_wrapping_a_captured_callable_is_detected(language):
    source, path = SOURCES[language]
    matches = detect(language, source, path)
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    assert bindings['$factory'] != bindings['$wrapper']
    assert bindings['$inner'].startswith(bindings['$factory'] + '/PARAMETER:')
    assert '/CALLABLE:' in bindings['$wrapper']


def test_renamed_callables_preserve_detection():
    assert len(detect('python', RENAMED_PYTHON, 'd.py')) == 1


def test_factory_returning_the_callable_unchanged_is_rejected():
    assert not detect('python', RETURNS_INNER_DIRECTLY, 'd.py')


def test_wrapper_that_never_invokes_the_capture_is_rejected():
    assert not detect('python', NEVER_INVOKES, 'd.py')


def test_wrapper_invoking_another_callable_is_rejected():
    assert not detect('python', INVOKES_ANOTHER_CALLABLE, 'd.py')


def test_wrapper_not_forwarding_its_argument_is_rejected():
    """The captured callable must receive the wrapper's own argument."""
    assert not detect('python', DROPS_THE_ARGUMENT, 'd.py')


def test_factory_without_a_callable_parameter_is_rejected():
    assert not detect('python', NO_PARAMETER_TO_CAPTURE, 'd.py')


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'decorator')
    row = next(v for v in rule.variants if v['id'] == 'callable-wrapper')
    assert sorted(row['languages']) == sorted(SOURCES)
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'captures: $inner' in row['query'] and 'call $inner' in row['query']
    assert 'edge ' not in row['query'] and 'walk ' not in row['query']

@pytest.mark.parametrize('language',sorted(SOURCES))
def test_unrelated_argument_rejects_each_language(language):
    source,path=SOURCES[language]
    source=source.replace('inner(value)','inner(0)').replace('inner.applyAsInt(value)','inner.applyAsInt(0)')
    assert not detect(language,source,path)


def test_rust_tail_closure_return_belongs_to_factory_not_closure():
    source,path=SOURCES['rust']
    graph=link_project([lower_source(source,'rust',path)])
    closure=next(e for e in graph.entities.values() if e.kind=='CALLABLE' and e.name.startswith('anonymous'))
    returns=[f for f in graph.facts if f.relation=='RETURN_OPERAND' and f.object==closure.id]
    assert len(returns)==1
    operation=next(o for o in graph.operations if o.id==returns[0].subject)
    factory=next(e for e in graph.entities.values() if e.kind=='CALLABLE' and e.name=='traced')
    assert operation.owner==factory.id
    assert all(o.owner==closure.id for o in graph.operations if o.kind=='RETURN' and o.id!=operation.id)


@pytest.mark.parametrize('mutation',['unrelated_macro','dead_macro','discarded_closure'])
def test_rust_macro_responsibility_and_returned_closure_are_required(mutation):
    source,path=SOURCES['rust']
    if mutation=='unrelated_macro':source=source.replace('println!','unrelated!')
    if mutation=='dead_macro':
        source=source.replace('println!("before");','').replace('println!("after");','').replace('        result','        return result;\n        println!("dead");')
    if mutation=='discarded_closure':source=source.replace('    move |','    let ignored = move |').replace('    }\n}', '    };\n    inner\n}')
    assert not detect('rust',source,path)


def test_java_homonymous_nonfunctional_receiver_is_not_a_callable_wrapper():
    source,path=SOURCES['java']
    source=source.replace('import java.util.function.IntUnaryOperator;','interface IntUnaryOperator { int applyAsInt(int x); void close(); }')
    assert not detect('java',source,path)
