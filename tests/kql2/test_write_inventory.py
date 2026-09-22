"""Write-inventory predicates: linear bodies versus guarded or indirect writes.

``linear_members`` is true only when the linear analysis proved the callable's member
writes; a branch, an indirect write or an unresolved scope publishes ``unsupported``
with a reason. ``final_member_input`` names the last write of an unmutated parameter
into a field, which is the evidence a configuration step contributes to its product.
"""
import pytest

from ken.kql2.service import search

LINEAR = '''language "kql/2"; module t; query q {
 type $assembly {
   field $state { }
   method $step {
     param $configured { }
     body { $state = $configured as $write; }
   }
 }
 where linear_members($step);
 select $step.name;
}'''

FINAL = '''language "kql/2"; module t; query q {
 type $assembly {
   field $state { }
   method $step {
     param $configured { }
     body { $state = $configured as $write; }
   }
 }
 where final_member_input($write, $configured);
 select $step.name;
}'''


def run(tmp_path, extension, source, query):
    (tmp_path / f'a.{extension}').write_text(source)
    return search(tmp_path, query, cache_mb=0)


@pytest.mark.parametrize('extension,source', [
    ('py', 'class Assembly:\n def configure(self, value): self.state = value\n'),
    ('java', 'class Assembly { int state; void configure(int value) { this.state = value; } }'),
    ('go', 'package a\ntype Assembly struct{state int}\n'
           'func(a *Assembly) configure(value int){a.state=value}\n'),
])
def test_linear_member_write_is_supported(tmp_path, extension, source):
    assert run(tmp_path, extension, source, LINEAR)['rows'] == [['configure']]


@pytest.mark.parametrize('extension,source', [
    ('py', 'class Assembly:\n def configure(self, value):\n  if value > 0:\n   self.state = value\n'),
    ('java', 'class Assembly { int state; void configure(int value) { if (value > 0) { this.state = value; } } }'),
    ('go', 'package a\ntype Assembly struct{state int}\n'
           'func(a *Assembly) configure(value int){if value>0 {a.state=value}}\n'),
])
def test_a_guarded_write_is_not_proven_linear(tmp_path, extension, source):
    assert run(tmp_path, extension, source, LINEAR)['rows'] == []


def test_rebinding_the_parameter_afterwards_is_not_the_final_input(tmp_path):
    source = 'class Assembly:\n def configure(self, value):\n  self.state = value\n  value = 0\n'
    assert run(tmp_path, 'py', source, FINAL)['rows'] == []


def test_the_last_write_of_an_unchanged_parameter_is_the_final_input(tmp_path):
    source = 'class Assembly:\n def configure(self, value):\n  self.state = 0\n  self.state = value\n'
    assert run(tmp_path, 'py', source, FINAL)['rows'] == [['configure']]
