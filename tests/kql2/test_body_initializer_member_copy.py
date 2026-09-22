"""``body { initializer { $state = $source; } }`` reads a member of the parameter.

The C++ copy constructor states its field copy in the declaration phase
(``Config(const Config& other) : value(other.value)``), where the analysis reads a
member of the other instance rather than a direct value. The clause is the same one
the Python/Java assignment constructors use; the member spelling is evidence, and a
constant initializer (``: value(0)``) is not.
"""
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

QUERY = '''language "kql/2";
module ken.probe;

pattern detect(out TypeDecl $unit) {
  type $unit {
    field $state {}
    method $constructor {
      constructor: true;
      arity: 1;
      param $source { reference_kind: "lvalue"; type: nominal($unit); }
      body { initializer { $state = $source; } }
    }
  }
}

query results {
  use detect(unit: $unit);
  select $unit;
}
'''

COPIES = '''class Config {
    int value;
public:
    Config() : value(1) {}
    Config(const Config& other) : value(other.value) {}
};
'''

CONSTANT = COPIES.replace('value(other.value)', 'value(0)')


def matches(source):
    graph = link_project([lower_source(source, 'cpp', 'f.cpp')])
    rule = SavedRule(id='probe', name='probe', query=QUERY, source=QUERY, query_language='kql/2')
    return execute_rules(graph, [rule], evidence_mode='strict')['matches']


def test_the_declaration_phase_copy_of_a_parameter_member_matches():
    assert matches(COPIES)


def test_a_constant_initializer_is_not_the_parameter_state():
    assert not matches(CONSTANT)
