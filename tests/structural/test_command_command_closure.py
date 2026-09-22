"""Command ``command-closure``: a queued closure invoked later with a context.

The variant is a published rule, so the test goes through the registry name
``command#command-closure``.

The identity of the queued closure is followed through whatever each language uses
to hold it: the closure itself (Python), a local alias (JavaScript, TypeScript,
Java, C#, C++) or a single-argument wrapper such as ``Box::new`` (Rust). The
execution context is a parameter of the invoker, and the closure must take at
least one parameter: arity zero is deliberately not imposed.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'command#command-closure'

SOURCES = {
    'python': ('''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return payload + context
        self.pending.append(action)
    def run(self, context):
        for action in self.pending:
            action(context)
''', 'c.py'),
    'javascript': ('''class Dispatcher {
  constructor() { this.pending = []; }
  submit(payload) {
    const action = (context) => payload + context;
    this.pending.push(action);
  }
  run(context) {
    for (const action of this.pending) { action(context); }
  }
}
''', 'c.js'),
    'typescript': ('''class Dispatcher {
  pending: ((c: number) => number)[] = [];
  submit(payload: number): void {
    const action = (context: number): number => payload + context;
    this.pending.push(action);
  }
  run(context: number): void {
    for (const action of this.pending) { action(context); }
  }
}
''', 'c.ts'),
    'java': ('''import java.util.ArrayList;
import java.util.List;
import java.util.function.IntUnaryOperator;
class Dispatcher {
  private final List<IntUnaryOperator> pending = new ArrayList<>();
  void submit(int payload) {
    IntUnaryOperator action = context -> payload + context;
    pending.add(action);
  }
  void run(int context) {
    for (IntUnaryOperator action : pending) {
      action.applyAsInt(context);
    }
  }
}
''', 'D.java'),
    'csharp': ('''using System;
using System.Collections.Generic;
class Dispatcher {
  private List<Func<int,int>> pending = new List<Func<int,int>>();
  void Submit(int payload) {
    Func<int,int> action = context => payload + context;
    pending.Add(action);
  }
  void Run(int context) {
    foreach (var action in pending) {
      int result = action(context);
    }
  }
}
''', 'D.cs'),
    'cpp': ('''#include <functional>
#include <vector>
class Dispatcher {
  std::vector<std::function<int(int)>> pending;
 public:
  void submit(int payload) {
    auto action = [payload](int context) { return payload + context; };
    pending.push_back(action);
  }
  void run(int context) {
    for (auto &action : pending) { action(context); }
  }
};
''', 'd.cpp'),
    'go': ('''package command

type Dispatcher struct {
	pending []func(int) int
}

func (d *Dispatcher) Submit(payload int) {
	action := func(context int) int { return payload + context }
	d.pending = append(d.pending, action)
}

func (d *Dispatcher) Run(context int) {
	for _, action := range d.pending {
		action(context)
	}
}
''', 'd.go'),
    'rust': ('''pub struct Dispatcher {
    pending: Vec<Box<dyn Fn(i32) -> i32>>,
}

impl Dispatcher {
    pub fn new() -> Dispatcher {
        Dispatcher { pending: Vec::new() }
    }
    pub fn submit(&mut self, payload: i32) {
        let action = move |context: i32| payload + context;
        self.pending.push(Box::new(action));
    }
    pub fn run(&self, context: i32) {
        for action in &self.pending {
            action(context);
        }
    }
}
''', 'd.rs'),
}

IMMEDIATE_ONLY = '''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return payload + context
        return action(0)
    def run(self, context):
        for action in self.pending:
            action(context)
'''

WRONG_PAYLOAD = '''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return context
        self.pending.append(action)
    def run(self, context):
        for action in self.pending:
            action(context)
'''

NO_CONTEXT_PARAMETER = '''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action():
            return payload
        self.pending.append(action)
    def run(self, context):
        for action in self.pending:
            action()
'''

NEVER_ITERATED = '''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return payload + context
        self.pending.append(action)
    def other(self):
        return 0
'''

DIFFERENT_QUEUE = '''class Dispatcher:
    def __init__(self):
        self.pending = []
        self.other = []
    def submit(self, payload):
        def action(context):
            return payload + context
        self.pending.append(action)
    def run(self, context):
        for action in self.other:
            action(context)
'''

NO_EXECUTION_CONTEXT = '''class Dispatcher:
    def __init__(self):
        self.pending = []
    def submit(self, payload):
        def action(context):
            return payload + context
        self.pending.append(action)
    def run(self):
        for action in self.pending:
            action(0)
'''


def detect(language, source, path):
    graph = link_project([lower_source(source, language, path)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', sorted(SOURCES))
def test_queued_closure_invoked_with_execution_context_is_detected(language):
    source, path = SOURCES[language]
    matches = detect(language, source, path)
    assert len(matches) == 1, language
    bindings = matches[0]['bindings']
    assert bindings['$submit'] != bindings['$run']
    assert bindings['$queue'] != bindings['$action']


def test_closure_called_immediately_without_being_queued_is_rejected():
    """The ficha's counterexample: an immediate call is not deferred work."""
    assert not detect('python', IMMEDIATE_ONLY, 'c.py')


def test_closure_not_reading_the_captured_payload_is_rejected():
    assert not detect('python', WRONG_PAYLOAD, 'c.py')


def test_closure_with_arity_zero_is_rejected():
    """The command receives context when it runs, so arity zero cannot match."""
    assert not detect('python', NO_CONTEXT_PARAMETER, 'c.py')


def test_queue_never_iterated_is_rejected():
    assert not detect('python', NEVER_ITERATED, 'c.py')


def test_invoker_iterating_another_collection_is_rejected():
    assert not detect('python', DIFFERENT_QUEUE, 'c.py')


def test_invoker_without_an_execution_context_is_rejected():
    assert not detect('python', NO_EXECUTION_CONTEXT, 'c.py')


def test_variant_is_ready_for_all_eight_declared_languages():
    rule = next(r for r in _load_catalog() if r.id == 'command')
    row = next(v for v in rule.variants if v['id'] == 'command-closure')
    assert sorted(row['languages']) == sorted(SOURCES)
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'captures: $local_payload' in row['query']
    assert 'iterate $queue as $local_element' in row['query']
