"""Iterator ``delegated-cursor``: the stored cursor is advanced by the call ``__next__`` returns.

The legacy query read raw facts (``RETURNS_CALL`` then ``ADVANCES_ITERATOR``) to
describe Python's ``return next(self.values)``. The migrated entry says the same
thing with selectors plus one predicate:

* ``field $cursor`` is the stored iterator the cursor delegates to,
* ``method $next`` holds a body ``let $local_result = call ... as $local_advance;``
  whose argument *is* that field, and returns that call's result,
* ``where advances($local_advance, $cursor)`` states the delegation the semantic
  layer accredits (``ADVANCES_ITERATOR``, model ``python-next``),
* ``where returns_self($iter, $iterator)`` is the ``__iter__`` half of the
  protocol, exactly as ``explicit-cursor`` reads it.

The design idea is delegation to a stored cursor, not "an iterator that mutates
its own index" (``explicit-cursor``) and not a generator. The negatives below are
the shapes that must stay out: a method whose name only *looks* like the protocol,
a ``__next__`` that returns the field itself, and a ``__next__`` that calls but
does not return the call's result.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'iterator#delegated-cursor'

STAFFED = '''class Cursor:
 def __init__(self, values): self.values=iter(values)
 def __iter__(self): return self
 def __next__(self): return next(self.values)
'''

CALL_NOT_RETURNED = '''class Cursor:
 def __init__(self, values): self.values=iter(values)
 def __iter__(self): return self
 def __next__(self):
  next(self.values)
  return 0
'''

FIELD_RETURNED_DIRECTLY = '''class Cursor:
 def __init__(self, values): self.values=iter(values)
 def __iter__(self): return self
 def __next__(self): return self.values
'''

ITER_DOES_NOT_RETURN_SELF = '''class Cursor:
 def __init__(self, values): self.values=iter(values)
 def __iter__(self): return self.values
 def __next__(self): return next(self.values)
'''

NON_PROTOCOL_NAMES = '''class Cursor:
 def __init__(self, values): self.values=iter(values)
 def iter(self): return self
 def next(self): return next(self.values)
'''

OWN_INDEX_CURSOR = '''class Subject:
 def __iter__(self): return self
 def __next__(self):
  self.index = self.index + 1
  return self.index
'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'iterator')
    return next(v for v in rule.variants if v['id'] == 'delegated-cursor')


def detect(source, language='python', rule=RULE):
    graph = link_project([lower_source(source, language, 'cursor.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


def test_a_stored_cursor_advanced_by_the_returned_call_is_detected():
    matches = detect(STAFFED)
    assert len(matches) == 1, matches
    assert '/CLASS:Cursor' in matches[0]['bindings']['$iterator']
    # The cursor is delegated to, not mutated: the sibling that reads observable
    # updates to its own field must stay out of this fixture.
    assert detect(STAFFED, rule='iterator#explicit-cursor') == []


@pytest.mark.parametrize('source', [CALL_NOT_RETURNED, FIELD_RETURNED_DIRECTLY,
                                    ITER_DOES_NOT_RETURN_SELF, NON_PROTOCOL_NAMES,
                                    OWN_INDEX_CURSOR])
def test_the_protocol_and_the_delegation_are_required(source):
    assert detect(source) == []
