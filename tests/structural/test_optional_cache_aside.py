"""Optional cache-aside uses an imported API and correlated nested consumers."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCE = '''import java.util.Optional;
class Service {
 Object find(Cache cache, Store store, String key) {
  return Optional.ofNullable(cache.get(key)).or(() -> {
   Optional<Object> loaded = Optional.ofNullable(store.load(key));
   loaded.ifPresent(item -> cache.set(key, item));
   return loaded;
  }).orElse(null);
 }
}'''


def run(source):
    graph = link_project([lower_source(source, 'java', 'sample.java')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.cache-aside', registry)], registry=registry)
    assert result['complete']
    return graph, result['matches']


def test_optional_cache_aside_and_renaming():
    _, hits = run(SOURCE)
    assert len(hits) == 1
    _, renamed = run(SOURCE.replace('cache', 'memo').replace('key', 'token').replace('item', 'entry'))
    assert len(renamed) == 1


@pytest.mark.parametrize('before,after', [
    ('cache.set(key, item)', 'other.set(key, item)'),
    ('cache.set(key, item)', 'cache.set(other, item)'),
    ('cache.set(key, item)', 'cache.set(key, other)'),
    ('store.load(key)', 'store.load(other)'),
    ('return loaded;', 'return other;'),
    ('loaded.ifPresent', 'other.ifPresent'),
    (').orElse(null)', ').orElseGet(other)'),
    ('cache.set(key, item)', 'cache.get(key)'),
])
def test_correlated_roles_reject_near_misses(before, after):
    _, hits = run(SOURCE.replace(before, after))
    assert not hits


@pytest.mark.parametrize('source', [
    SOURCE.replace('import java.util.Optional;', ''),
    SOURCE.replace('java.util.Optional', 'custom.Optional'),
    SOURCE.replace('import java.util.Optional;', 'import java.util.*;'),
    SOURCE.replace('import java.util.Optional;', 'import java.util.Optional; import custom.Optional;'),
    SOURCE.replace('class Service {', 'class Optional {} class Service {'),
    SOURCE.replace('String key)', 'String key, Object Optional)'),
    SOURCE.replace('class Service {', 'class Service { Object Optional;'),
    SOURCE.replace('Optional.ofNullable', 'other.Optional.ofNullable'),
])
def test_unresolved_or_shadowed_optional_has_no_api_facts(source):
    graph, hits = run(source)
    assert not hits
    assert not any(f.relation.startswith('OPTIONAL_') for f in graph.facts)


def test_reassignment_does_not_propagate_optional_type():
    source = SOURCE.replace('loaded.ifPresent', 'loaded = other; loaded.ifPresent')
    _, hits = run(source)
    assert not hits


def test_variant_can_be_selected_independently():
    graph = link_project([lower_source(SOURCE, 'java', 'sample.java')])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('architecture.cache-aside#java-optional', registry)], registry=registry)
    assert len(result['matches']) == 1 and result['complete']
