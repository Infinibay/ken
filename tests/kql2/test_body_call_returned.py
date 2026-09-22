"""``call $c { returned: true; }`` — the occurrence's value is what the method returns.

A copy primitive's *use* is not the copy protocol: ``directed/prototype-discarded-copy``
calls ``copy.copy(self)`` and throws the result away. The occurrence must be the
value the callable hands over, directly (Java ``(Config) super.clone()`` publishes
the returned operand as the cast of the call) or through Python's ``return``.
"""
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, execute_rules
from ken.structural.semantic import link_project

from tests.structural import test_prototype_language_copy as T

RECEIVER = '''language "kql/2";
module ken.probe;

pattern detect(out TypeDecl $unit) {
  type $unit {
    method $m {
      receiver $self {}
      body {
        call $copier { name: ["copy", "deepcopy", "clone", "MemberwiseClone"]; receiver: $self;
                      returned: true; resolution: unresolved; };
      }
    }
  }
}

query results {
  use detect(unit: $unit);
  select $unit;
}
'''

ARGUMENT = RECEIVER.replace('receiver: $self;\n                      ',
                            'argument $self at any;\n                      ')

DISCARDED = '''import copy
class Sample:
 def operation(self):
  copy.copy(self)
  return 0
'''


def matches(language, query, source):
    graph = link_project([lower_source(source, language, 'f.' + T.EXTENSIONS[language])])
    rule = SavedRule(id='probe', name='probe', query=query, source=query, query_language='kql/2')
    return execute_rules(graph, [rule], evidence_mode='strict')['matches']


def test_a_returned_instance_delegation_matches():
    assert matches('java', RECEIVER, T.positive('java'))
    assert matches('csharp', RECEIVER, T.positive('csharp'))
    assert matches('python', ARGUMENT, T.positive('python'))


def test_a_discarded_delegation_does_not_match():
    assert not matches('python', ARGUMENT, DISCARDED)


def test_a_delegation_on_a_field_is_not_the_instance():
    assert not matches('java', RECEIVER, T.JAVA_FIELD_CLONE)
    assert not matches('csharp', RECEIVER, T.CSHARP_FIELD_CLONE)
    assert not matches('python', ARGUMENT, T.PY_FOREIGN_CONTAINER)
