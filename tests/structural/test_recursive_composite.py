"""Nominal recursive collections need no separate inheritance hierarchy."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCES = {
 'go': 'package p; type Node struct { children []*Node }; func(n *Node) Walk(){ for _, child := range n.children { child.Walk() } }',
 'python': 'class Node:\n children: list[Node]\n def Walk(self):\n  for child in self.children:\n   child.Walk()\n',
 'java': 'class Node { List<Node> children; void Walk(){ for(Node child: children){ child.Walk(); } } }',
 'typescript': 'class Node { children: Array<Node>; Walk(){ for(const child of this.children){ child.Walk(); } } }',
 'csharp': 'class Node { List<Node> children; void Walk(){ foreach(Node child in children){ child.Walk(); } } }',
}


def matches(source, language):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('composite', registry)], registry=registry)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_recursive_collection(language):
    assert matches(SOURCES[language], language)
    assert matches(SOURCES[language].replace('Node', 'Branch').replace('Walk', 'Visit'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_other_child_operation_is_not_recursive_composite(language):
    assert not matches(SOURCES[language].replace('child.Walk()', 'child.Other()'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_call_on_other_receiver_is_not_iterated_child(language):
    assert not matches(SOURCES[language].replace('child.Walk()', 'other.Walk()'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_unrelated_element_type_is_not_self_recursion(language):
    source = SOURCES[language].replace('[]*Node', '[]*Other').replace('list[Node]', 'list[Other]').replace('List<Node>', 'List<Other>').replace('Array<Node>', 'Array<Other>')
    if language == 'go': source = source.replace('package p;', 'package p; type Other struct {};')
    elif language == 'python': source = 'class Other: pass\n' + source
    else: source = 'class Other {}\n' + source
    assert not matches(source, language)


def test_go_index_slot_is_not_child():
    assert not matches(SOURCES['go'].replace('_, child', 'child, _'), 'go')


def test_go_value_slice_also_supports_nominal_recursion():
    assert matches(SOURCES['go'].replace('[]*Node', '[]Node'), 'go')
