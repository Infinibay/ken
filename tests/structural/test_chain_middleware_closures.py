"""Chain of Responsibility ``middleware-closures``: a captured ``next`` behind a branch.

The variant is a published rule, so the test goes through the registry name
``chain-of-responsibility#middleware-closures`` rather than a private copy of the query.

``linked-handlers`` covers the object form: a handler holding a successor of the same
contract and forwarding conditionally. This variant is the closure form, and its whole
content is that the capture alone is not enough -- ``decorator#callable-wrapper``
already covers a wrapper that captures and always forwards. What makes it a chain link
is that the forwarding is **guarded by a branch**, so the handler can also return
without forwarding.

One shape needs saying explicitly. Rust spells the continuing arm as a tail expression
(``next(request)`` with no ``return``), so there is no ``RETURN_OPERAND`` to read; the
call *is* the branch's successor operation, which ``SYNTAX_NODE`` states. Both spellings
are accepted, and both are exercised.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'chain-of-responsibility#middleware-closures'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}

SOURCES = {
    'python': '''def middleware(next_handler):
    def handle(request):
        if not request.authenticated:
            return "denied"
        return next_handler(request)
    return handle
''',
    'javascript': '''function middleware(next) {
  return function handle(request) {
    if (!request.authenticated) {
      return "denied";
    }
    return next(request);
  };
}
''',
    'typescript': '''function middleware(next: (r: string) => string): (r: string) => string {
  return function handle(request: string): string {
    if (request.length === 0) {
      return "denied";
    }
    return next(request);
  };
}
''',
    'java': '''import java.util.function.Function;

class Middleware {
    static Function<String, String> middleware(Function<String, String> next) {
        return request -> {
            if (request.isEmpty()) {
                return "denied";
            }
            return next.apply(request);
        };
    }
}
''',
    'csharp': '''using System;

class Middleware {
    static Func<string, string> Wrap(Func<string, string> next) {
        return request => {
            if (request.Length == 0) {
                return "denied";
            }
            return next(request);
        };
    }
}
''',
    'cpp': '''#include <functional>
#include <string>

std::function<std::string(std::string)> middleware(std::function<std::string(std::string)> next) {
    return [next](std::string request) -> std::string {
        if (request.empty()) {
            return "denied";
        }
        return next(request);
    };
}
''',
    'go': '''package chain

func Middleware(next func(string) string) func(string) string {
\treturn func(request string) string {
\t\tif request == "" {
\t\t\treturn "denied"
\t\t}
\t\treturn next(request)
\t}
}
''',
    # The tail expression is the continuation; there is no `return` to read.
    'rust': '''fn middleware(next: fn(&str) -> String) -> impl Fn(&str) -> String {
    move |request: &str| {
        if request.is_empty() {
            return "denied".to_string();
        }
        next(request)
    }
}
''',
}

# The same fixtures with the guard removed: a wrapper, not a chain link.
NO_BRANCH = {
    'python': '''def middleware(next_handler):
    def handle(request):
        return next_handler(request)
    return handle
''',
    'javascript': '''function middleware(next) {
  return function handle(request) {
    return next(request);
  };
}
''',
    'typescript': '''function middleware(next: (r: string) => string): (r: string) => string {
  return function handle(request: string): string {
    return next(request);
  };
}
''',
    'java': '''import java.util.function.Function;

class Middleware {
    static Function<String, String> middleware(Function<String, String> next) {
        return request -> {
            return next.apply(request);
        };
    }
}
''',
    'csharp': '''using System;

class Middleware {
    static Func<string, string> Wrap(Func<string, string> next) {
        return request => {
            return next(request);
        };
    }
}
''',
    'cpp': '''#include <functional>
#include <string>

std::function<std::string(std::string)> middleware(std::function<std::string(std::string)> next) {
    return [next](std::string request) -> std::string {
        return next(request);
    };
}
''',
    'go': '''package chain

func Middleware(next func(string) string) func(string) string {
\treturn func(request string) string {
\t\treturn next(request)
\t}
}
''',
    'rust': '''fn middleware(next: fn(&str) -> String) -> impl Fn(&str) -> String {
    move |request: &str| {
        next(request)
    }
}
''',
}

PY_NEVER_DELEGATES = '''def middleware(next_handler):
    def handle(request):
        if request.admin:
            return "a"
        return "b"
    return handle
'''

PY_NOT_RETURNED = '''def middleware(next_handler):
    def handle(request):
        if request.blocked:
            return "denied"
        next_handler(request)
        return "done"
    return handle
'''

PY_NO_CAPTURE = '''def middleware():
    def handle(request):
        if request.blocked:
            return "denied"
        return global_handler(request)
    return handle
'''

PY_BOTH_ARMS_DELEGATE = '''def middleware(next_handler):
    def handle(request):
        if request.admin:
            return next_handler("a")
        return next_handler("b")
    return handle
'''

# The same residual shape in the languages whose invocation form differs:
# Java and C# call the captured delegate through a method, so the counted callee
# name is the method's, not the parameter's.
BOTH_ARMS_DELEGATE = {
    'javascript': '''function middleware(next) {
  return function handle(request) {
    if (request.admin) { return next("a"); }
    return next("b");
  };
}
''',
    'java': '''import java.util.function.Function;

class Middleware {
    static Function<String, String> middleware(Function<String, String> next) {
        return request -> {
            if (request.isEmpty()) { return next.apply("a"); }
            return next.apply("b");
        };
    }
}
''',
    'go': '''package chain

func Middleware(next func(string) string) func(string) string {
\treturn func(request string) string {
\t\tif request == "" { return next("a") }
\t\treturn next("b")
\t}
}
''',
}


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'chain-of-responsibility')
    return next(v for v in rule.variants if v['id'] == 'middleware-closures')


def detect(language, source):
    graph = link_project([lower_source(source, language,
                                       f'chain.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_a_branch_guarded_forwarding_closure_is_detected(language):
    matches = detect(language, SOURCES[language])
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    # The shared role with the object variant is the handler.
    assert '/CALLABLE:' in bindings['$unit']
    assert bindings['$factory'] != bindings['$unit']
    assert bindings['$next'] != bindings['$unit']


@pytest.mark.parametrize('language', LANGUAGES)
def test_an_unconditional_wrapper_is_rejected(language):
    """Without a branch this is decorator#callable-wrapper, not a chain link."""
    assert not detect(language, NO_BRANCH[language]), language


def test_a_handler_that_never_forwards_is_rejected():
    assert not detect('python', PY_NEVER_DELEGATES)


def test_a_handler_that_does_not_yield_the_forwarded_result_is_rejected():
    assert not detect('python', PY_NOT_RETURNED)


def test_a_handler_that_does_not_capture_next_is_rejected():
    assert not detect('python', PY_NO_CAPTURE)


@pytest.mark.parametrize('language', sorted(BOTH_ARMS_DELEGATE))
def test_a_branch_that_forwards_on_both_outcomes_is_rejected(language):
    """Every path forwards, so no terminating arm exists: still a wrapper.

    This was the measured residual of the previous commit, where it matched. It is
    closed by ``complete:<callable>:HAS_CALL`` (IR 1.61) plus an exact count of calls
    sharing the delegate's callee name.
    """
    assert not detect(language, BOTH_ARMS_DELEGATE[language]), language


def test_the_python_double_forwarding_shape_is_rejected():
    assert not detect('python', PY_BOTH_ARMS_DELEGATE)


def test_unrelated_calls_do_not_count_towards_the_delegation():
    """The count is scoped by callee name, so logging does not break the match."""
    assert detect('python', '''def middleware(next_handler):
    def handle(request):
        if not request.authenticated:
            return "denied"
        log(request)
        audit(request)
        return next_handler(request)
    return handle
''')


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    # The capture, the branch guard and the yielded delegation are stated in KQL 2.
    assert 'captures: $next' in row['query']
    assert 'if (_) { return _; }' in row['query']
    assert 'return $delegated;' in row['query']
    assert 'excluido' in row['query_claim']


def test_the_rust_tail_expression_is_the_continuation():
    """Rust has no ``return`` in the continuing arm; ``SYNTAX_NODE`` states it instead."""
    graph = link_project([lower_source(SOURCES['rust'], 'rust', 'chain.rs')])
    assert not graph.diagnostics, graph.diagnostics
    tail = [op for op in graph.operations if op.native_kind == 'call_expression'
            and op.attrs.get('tokens') == []]
    assert tail, 'the fixture must contain the tail call'
