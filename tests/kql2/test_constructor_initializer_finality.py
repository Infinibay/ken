"""The constructor initializer claim is terminal: a later body write refutes it.

``constructor $ctor { parameters { param $input {} } body { initializer { $field = $input; } } }``
says the field's input is the parameter. ``docs/design/kql2/catalog-extensions.md`` (F4):
a TypeScript parameter property publishes the declaration-phase claim
(``PARAMETER_INITIALIZES_FIELD``) and no ``CONSTRUCTOR_FIELD_INPUT``, so the clause must
consult the executed body write itself — otherwise a constructor that assigns ``null``
over the parameter property still satisfies it. The assignment-style languages take the
``CONSTRUCTOR_FIELD_INPUT`` branch, which withholds the claim on exactly that overwrite.
"""
from __future__ import annotations

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from ken.structural.semantic import link_project

QUERY = ('language "kql/2"; module t;\n'
         'pattern detect(out GraphTerm $unit) {\n'
         '  type $unit {\n'
         '    field $receiver {}\n'
         '    constructor $ctor {\n'
         '      parameters { param $input {} }\n'
         '      body { initializer { $receiver = $input; } }\n'
         '    }\n'
         '  }\n'
         '}\n'
         'query results { use detect(unit: $unit); select $unit; }\n')

TS = ('class Sink { write(value: number) { } }\n'
      'class Job { constructor(private receiver: Sink) { } '
      'run() { this.receiver.write(1); } }\n')

PYTHON = ('class Sink:\n def write(self, value): pass\n'
          'class Job:\n def __init__(self, receiver: Sink):\n  self.receiver = receiver\n'
          ' def run(self):\n  self.receiver.write(1)\n')


def matches(source: str, language: str) -> int:
    graph = link_project([lower_source(source, language, 'sample.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    rule = SavedRule(id='t', name='t', query=QUERY, source=QUERY, query_language='kql/2')
    result = execute_rules(graph, [rule], registry=builtin_rules())
    assert result['complete'], result
    return len(result['matches'])


def test_parameter_property_initializes_the_field():
    assert matches(TS, 'typescript') == 1


def test_parameter_property_overwritten_by_the_body_is_not_terminal():
    overwritten = TS.replace('constructor(private receiver: Sink) { }',
                             'constructor(private receiver: Sink) { this.receiver = null; }')
    assert overwritten != TS
    assert matches(overwritten, 'typescript') == 0


def test_assignment_initializer_still_matches():
    assert matches(PYTHON, 'python') == 1


def test_assignment_initializer_followed_by_an_overwrite_does_not_match():
    overwritten = PYTHON.replace('  self.receiver = receiver\n',
                                 '  self.receiver = receiver\n  self.receiver = None\n')
    assert overwritten != PYTHON
    assert matches(overwritten, 'python') == 0
