"""``initializer $field from $value`` — the value a construction stores.

A Go keyed literal (``&Task{action: func(){ ... }}``) initializes a field with a
value that never passes through a parameter: the frontend publishes
``INITIALIZES_FIELD(keyed_element, field)`` and ``STORES_VALUE(keyed_element, closure)``.
``initializer $field;`` alone claims only that the construction stores the *field*
itself, which a keyed literal never does, so the operand ``from $value`` names the
value the literal carries.

The closure's own body is what states what the captured binding is used for, which
is why ``captures: $bound`` binds ``$bound`` for the owner's clauses (see
``docs/design/kql2/catalog-extensions.md`` 5.2) and why a ``call`` clause that names
an argument is anchored by the call occurrence (5.3).
"""
from __future__ import annotations

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from ken.structural.semantic import link_project


def query(branch: str, closure_body: str = 'call $inner { argument $bound at any; } as $use;') -> str:
    return ('language "kql/2"; module t;\n'
            'pattern detect(out GraphTerm $unit) {\n'
            '  type $unit {\n'
            '    field $action {}\n'
            '    method $invoke { constructor: false; body { call $action {} as $dispatch; } }\n'
            '  }\n'
            '  callable $closure {\n'
            '    constructor: false;\n'
            '    captures: $bound;\n'
            f'    body {{ {closure_body} }}\n'
            '  }\n'
            '  callable $producer {\n'
            '    constructor: false;\n'
            f'    body {{ let $made = construct $unit {{ {branch} }} as $new; }}\n'
            '  }\n'
            '}\n'
            'query results { use detect(unit: $unit); select $unit; }\n')


GO = ('package p; type Task struct{ action func() }; '
      'func New(data string)*Task { return &Task{action: func(){ work(data) }} }; '
      'func(t *Task) Run(){t.action()}')


def matches(source: str = GO, language: str = 'go', **kwargs) -> int:
    graph = link_project([lower_source(source, language, 'sample')])
    text = query(**kwargs)
    rule = SavedRule(id='t', name='t', query=text, source=text, query_language='kql/2')
    result = execute_rules(graph, [rule], registry=builtin_rules())
    assert result['complete'], result
    return len(result['matches'])


def test_named_value_matches_a_keyed_literal():
    assert matches(branch='initializer $action from $closure;') == 1


def test_field_without_the_stored_value_does_not_match():
    # The literal stores the closure, not the field: without ``from`` the clause is
    # asking the construction to store the field itself.
    assert matches(branch='initializer $action;') == 0


def test_the_stored_value_must_be_the_closure_that_captures():
    # ``work()`` captures nothing, so the closure the literal stores is not the one
    # the pattern bound.
    assert matches(GO.replace('work(data)', 'work()'), branch='initializer $action from $closure;') == 0


def test_the_capture_must_reach_a_call():
    # ``_ = data`` reads the captured binding without passing it anywhere: the
    # captured value is not an argument of any call.
    assert matches(GO.replace('work(data)', '_ = data'), branch='initializer $action from $closure;') == 0


def test_capture_in_the_wrong_argument_position_does_not_match():
    assert matches(branch='initializer $action from $closure;',
                   closure_body='call $inner { argument $bound at 1; } as $use;') == 0


def test_a_call_clause_still_needs_evidence():
    # Nothing names the callee and no argument is stated, so the occurrence carries
    # no claim: an unconstrained ``call`` does not bind.
    assert matches(branch='initializer $action from $closure;',
                   closure_body='call $inner {} as $use;') == 0
