"""Composite algorithm contracts, including explicit gaps in the signature query.

These fixtures are parsed, never executed. Strict xfails specify behavior that
the present structural signature cannot distinguish from a valid algorithm.
"""
import re

import pytest

from .contract_support import contract_matches

from ken.structural import lower_instructions
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


SOURCES = {
    'python': '''class Node:
 children: list[Node]
 def Count(self, context: int):
  total = context
  for child in self.children:
   value = child.Count(context)
   total = total + value
  return total
''',
    'java': '''import java.util.List;
class Node {
 List<Node> children;
 int Count(int context) {
  int total = context;
  for (Node child : this.children) {
   int value = child.Count(context);
   total = total + value;
  }
  return total;
 }
}''',
    'typescript': '''class Node {
 children: Array<Node> = [];
 Count(context: number): number {
  let total = context;
  for (let child of this.children) {
   const value = child.Count(context);
   total = total + value;
  }
  return total;
 }
}''',
}


def instrument(source, language):
    if language == 'python':
        return source.replace('   value =', '   marker = 1 + 2\n   print(marker)\n   value =').replace(
            '  return total', '  print(123)\n  return total')
    logging = 'System.out.println(marker);' if language == 'java' else 'console.log(marker);'
    declaration = 'int' if language == 'java' else 'const'
    source = source.replace('   ' + ('int' if language == 'java' else 'const') + ' value =',
                            f'   {declaration} marker = 1 + 2; {logging}\n   ' +
                            ('int' if language == 'java' else 'const') + ' value =')
    return source


def detect(source, language):
    graph = link_project([lower_source(source, language, 'composite.' + {
        'python': 'py', 'java': 'java', 'typescript': 'ts'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('composite', registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return graph, result['matches']


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mode', ['baseline', 'noise', 'renamed'])
def test_recursive_aggregation_survives_independent_work(language, mode):
    source = SOURCES[language]
    if mode != 'baseline':
        source = instrument(source, language)
    if mode == 'renamed':
        for old, new in [('Node', 'Part'), ('Count', 'Measure'), ('children', 'parts')]:
            source = re.sub(r'\b' + old + r'\b', new, source)
    graph, matches = detect(source, language)
    assert matches
    assert {graph.entities[m['bindings']['$unit']].name for m in matches} == {
        'Part' if mode == 'renamed' else 'Node'}
    lower_instructions(graph).verify()


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['other-operation', 'fixed-receiver', 'unrelated-elements', 'no-recursion'])
def test_broken_recursive_collaboration_is_rejected(language, mutation):
    source = instrument(SOURCES[language], language)
    if mutation == 'other-operation':
        source = source.replace('child.Count(context)', 'child.Other(context)')
    elif mutation == 'fixed-receiver':
        source = source.replace('child.Count(context)', ('self' if language == 'python' else 'this') + '.Count(context)')
    elif mutation == 'unrelated-elements':
        source = source.replace('list[Node]', 'list[Other]').replace('List<Node>', 'List<Other>').replace('Array<Node>', 'Array<Other>')
        source = ('class Other:\n pass\n' if language == 'python' else 'class Other {}\n') + source
    else:
        source = source.replace('child.Count(context)', '0')
    assert not detect(source, language)[1]


@pytest.mark.parametrize('language', SOURCES)
def test_iterating_external_collection_does_not_use_stored_children(language):
    source = instrument(SOURCES[language], language)
    if language == 'python':
        source = source.replace('context: int)', 'context: int, others: list[Node])').replace('in self.children:', 'in others:').replace('child.Count(context)', 'child.Count(context, others)')
    elif language == 'java':
        source = source.replace('int context)', 'int context, List<Node> others)').replace(': this.children)', ': others)').replace('child.Count(context)', 'child.Count(context, others)')
    else:
        source = source.replace('context: number)', 'context: number, others: Array<Node>)').replace('of this.children)', 'of others)').replace('child.Count(context)', 'child.Count(context, others)')
    assert not detect(source, language)[1]


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['discard-result', 'replace-context'])
def test_requested_aggregate_contract_rejects_broken_value_flow(language, mutation):
    source = instrument(SOURCES[language], language)
    source = source.replace('total = total + value', 'total = total + 0') if mutation == 'discard-result' else source.replace('child.Count(context)', 'child.Count(0)')
    assert contract_matches(instrument(SOURCES[language], language), language, 'composite.additive_aggregate')
    assert not contract_matches(source, language, 'composite.additive_aggregate')


@pytest.mark.parametrize('language', SOURCES)
def test_rebound_child_is_not_the_iterated_element(language):
    source = instrument(SOURCES[language], language)
    if language == 'python':
        source = source.replace('   value =', '   child = self\n   value =')
    else:
        declaration = 'int' if language == 'java' else 'const'
        source = source.replace(f'   {declaration} value =', f'   child = this;\n   {declaration} value =')
    assert not detect(source, language)[1]
