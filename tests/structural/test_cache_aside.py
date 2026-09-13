"""Cache-aside requires correlated key, cache, loaded value and miss arm."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCES = {
 'python': 'def fetch(cache, source, key):\n value = cache.get(key)\n if value is None:\n  value = source.load(key)\n  cache.set(key, value)\n return value\n',
 'javascript': 'function fetch(cache, source, key) { let value = cache.get(key); if (value === null) { value = source.load(key); cache.set(key, value); } return value; }',
 'typescript': 'function fetch(cache: Cache, source: Store, key: string) { let value = cache.get(key); if (value === null) { value = source.load(key); cache.set(key, value); } return value; }',
 'java': 'class A { Object fetch(Cache cache, Store source, String key) { Object value = cache.get(key); if (value == null) { value = source.load(key); cache.set(key, value); } return value; }}',
 'csharp': 'class A { object Fetch(Cache cache, Store source, string key) { var value = cache.Get(key); if (value == null) { value = source.load(key); cache.Set(key, value); } return value; }}',
}


def matches(source, language):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    outcome = execute_rules(graph, [named_rule('architecture.cache-aside', registry)], registry=registry)
    assert outcome['complete']
    return outcome['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_null_miss_cache_aside(language):
    assert len(matches(SOURCES[language], language)) == 1


@pytest.mark.parametrize('language', SOURCES)
def test_renamed_roles(language):
    assert matches(SOURCES[language].replace('cache', 'memo').replace('key', 'token').replace('value', 'item'), language)


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('change', ['write_key', 'load_key', 'cache', 'value', 'hit_arm', 'return'])
def test_near_misses(language, change):
    source = SOURCES[language]
    if change == 'write_key': source = source.replace('(key, value)', '(other, value)')
    elif change == 'load_key': source = source.replace('load(key)', 'load(other)')
    elif change == 'cache': source = source.replace('cache.set', 'other.set').replace('cache.Set', 'other.Set')
    elif change == 'value': source = source.replace('(key, value)', '(key, other)')
    elif change == 'hit_arm':
        source = source.replace('is None', 'is not None')
        source = source.replace('=== null', '!== null') if '=== null' in source else source.replace('== null', '!= null')
    elif change == 'return': source = source.replace('return value', 'return other')
    assert not matches(source, language)


@pytest.mark.parametrize('language', ['javascript', 'typescript', 'java', 'csharp'])
def test_write_outside_miss_is_not_read_fill_variant(language):
    source = SOURCES[language].replace('cache.set(key, value); }', '} cache.set(key, value);').replace('cache.Set(key, value); }', '} cache.Set(key, value);')
    assert not matches(source, language)


def test_nested_function_load_not_executed_by_miss_arm():
    source = 'def fetch(cache, source, key):\n value = cache.get(key)\n if value is None:\n  def helper():\n   value = source.load(key)\n  cache.set(key, value)\n return value\n'
    assert not matches(source, 'python')


@pytest.mark.parametrize('language', SOURCES)
def test_reversed_null_comparison(language):
    source = SOURCES[language]
    source = source.replace('value is None', 'None is value').replace('value === null', 'null === value').replace('value == null', 'null == value')
    assert matches(source, language)


@pytest.mark.parametrize('language', ['javascript', 'typescript', 'java', 'csharp'])
def test_disjunction_does_not_prove_null_miss(language):
    source = SOURCES[language].replace('value === null', 'value === null || force').replace('value == null', 'value == null || force')
    assert not matches(source, language)


def test_csharp_initializer_with_comment_and_uninitialized_declaration():
    source = SOURCES['csharp'].replace('= cache.Get', '= /* lookup */ cache.Get')
    assert matches(source, 'csharp')
    assert not matches(source.replace('= /* lookup */ cache.Get(key)', ''), 'csharp')
