"""Execute a selected optional contract through the public saved-rule service."""
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules


def contract_matches(source, language, name):
    graph = link_project([lower_source(source, language, 'contract.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(name, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']
