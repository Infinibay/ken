"""Source-to-query regressions for architectural patterns, including near misses."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule, select_rules
from ken.structural.semantic import link_project


SOURCES = {
 'python': '''class Service:
 def run(self): pass
class Consumer:
 def configure(self, incoming: Service): self.dependency = incoming
 def handle(self): self.dependency.run()
''',
 'javascript': '''class Service { run() {} }
class Consumer {
 configure(incoming) { this.dependency = incoming; }
 handle() { this.dependency.run(); }
}''',
 'typescript': '''class Service { run(): void {} }
class Consumer {
 dependency: Service;
 configure(incoming: Service): void { this.dependency = incoming; }
 handle(): void { this.dependency.run(); }
}''',
 'java': '''class Service { void run() {} }
class Consumer {
 Service dependency;
 void configure(Service incoming) { this.dependency = incoming; }
 void handle() { this.dependency.run(); }
}''',
 'csharp': '''class Service { public void run() {} }
class Consumer {
 Service dependency;
 void configure(Service incoming) { this.dependency = incoming; }
 void handle() { this.dependency.run(); }
}''',
}


def search(source, language):
    graph = link_project([lower_source(source, language, 'example')])
    assert not graph.diagnostics
    rules = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.dependency-injection', rules)], registry=rules)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_injected_collaborator_and_renaming(language):
    assert search(SOURCES[language], language)
    assert search(SOURCES[language].replace('Consumer', 'X').replace('dependency', 'field')
                  .replace('configure', 'accept').replace('incoming', 'value'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_constructor_injection(language):
    source = SOURCES[language]
    if language == 'python':
        source = source.replace('configure', '__init__')
    elif language in {'java', 'csharp'}:
        source = source.replace('void configure', 'Consumer')
    else:
        source = source.replace('configure', 'constructor').replace('): void { this.dependency', ') { this.dependency')
    assert search(source, language)


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('mutation', ['different_field', 'local_construction', 'unused'])
def test_dependency_injection_near_misses(language, mutation):
    source = SOURCES[language]
    if mutation == 'different_field':
        source = source.replace('dependency.run()', 'other.run()')
    elif mutation == 'local_construction':
        source = source.replace('= incoming', '= Service()' if language == 'python' else '= new Service()')
    else:
        source = source.replace('self.dependency.run()', 'pass') if language == 'python' else source.replace('this.dependency.run();', '')
    assert not search(source, language)


def test_modern_collection_uses_public_rule_registry():
    registry = builtin_rules()
    assert 'architecture.dependency-injection' in {r.id for r in select_rules(registry, collections=['modern'])}
    assert len(select_rules(registry, collections=['gof'])) == 23
