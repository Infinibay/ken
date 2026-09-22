"""``call $c { name: [...] }`` — the primitive names a protocol is recognised under.

A protocol such as "copy the instance" is spelled differently in each language
library (``copy``/``deepcopy`` on Python's ``copy`` module, ``clone`` on Java and
Rust, ``MemberwiseClone`` on .NET). The call occurrence publishes its own
spelling, so the clause may state the alternatives.
"""
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

PYTHON = '''import copy

class Config:
    def __init__(self):
        self.value = 1

    def duplicate(self):
        return copy.deepcopy(self)
'''

QUERY = '''language "kql/2";
module ken.probe;

pattern detect(out TypeDecl $unit) {
  type $unit {
    method $m {
      constructor: false;
      body {
        let $replica = call $copier { name: %s; resolution: unresolved; } as $invocation;
      }
    }
  }
}

query results {
  use detect(unit: $unit);
  select $unit;
}
'''


def matches(names, source=PYTHON):
    graph = link_project([lower_source(source, 'python', 'f.py')])
    query = QUERY % names
    rule = SavedRule(id='probe', name='probe', query=query, source=query, query_language='kql/2')
    return execute_rules(graph, [rule], evidence_mode='strict')['matches']


def test_a_name_list_states_the_alternative_primitive_spellings():
    assert matches('["copy", "deepcopy"]')


def test_a_single_name_literal_is_unchanged():
    assert matches('"deepcopy"')
    assert not matches('"copy"')


def test_a_call_outside_the_stated_spellings_is_not_the_protocol():
    assert not matches('["clone", "MemberwiseClone"]')
