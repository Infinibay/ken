"""``method $m { completes: true; }`` — the callable's body reaches a normal exit.

``prototype#language-copy`` identifies the C++ copy constructor by its signature,
so a declaration whose body only throws (``Config(const Config& other) : value(other.value)
{ throw 0; }``) must state the other value: normal completion is what the body does
not have.
"""
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

QUERY = '''language "kql/2";
module ken.probe;

pattern detect(out TypeDecl $unit) {
  type $unit {
    method $constructor {
      constructor: true;
      arity: 1;
      completes: %s;
      param $source { reference_kind: "lvalue"; type: nominal($unit); }
    }
  }
}

query results {
  use detect(unit: $unit);
  select $unit;
}
'''

COMPLETES = '''class Config {
    int value;
public:
    Config() : value(1) {}
    Config(const Config& other) : value(other.value) {}
};
'''

THROWS = '''class Config {
    int value;
public:
    Config() : value(1) { throw 0; }
    Config(const Config& other) : value(other.value) { throw 0; }
};
'''


def matches(completes, source):
    graph = link_project([lower_source(source, 'cpp', 'f.cpp')])
    query = QUERY % completes
    rule = SavedRule(id='probe', name='probe', query=query, source=query, query_language='kql/2')
    return execute_rules(graph, [rule], evidence_mode='strict')['matches']


def test_a_copy_constructor_that_completes_matches():
    assert matches('true', COMPLETES)


def test_a_copy_constructor_whose_body_only_throws_does_not_match():
    assert not matches('true', THROWS)
    assert matches('false', THROWS)
