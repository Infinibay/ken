"""Keyed registration and invocation must share a table and argument roles."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules
from ken.structural.query import QueryBudget

SOURCES = {
 'python': 'class Registry:\n def register(self, key, handler): self.table[key] = handler\n def dispatch(self, requested, data): return self.table[requested](data)\n',
 'javascript': 'class Registry { register(key, handler) { this.table[key] = handler; } dispatch(requested, data) { return this.table[requested](data); } }',
 'typescript': 'class Registry { table: Record<string, (x:number)=>number>; register(key:string, handler:(x:number)=>number) { this.table[key] = handler; } dispatch(requested:string, data:number) { return this.table[requested](data); } }',
 'go': 'package p; type Registry struct { table map[string]func(int)int }; func(r *Registry) register(key string, handler func(int)int) { r.table[key] = handler }; func(r *Registry) dispatch(requested string, data int) int { return r.table[requested](data) }',
}


def matches(source, language):
    g = link_project([lower_source(source, language, 'example')])
    assert not g.diagnostics
    registry = builtin_rules()
    r = execute_rules(g, [named_rule('architecture.dispatch-table', registry)], registry=registry)
    assert r['complete']
    return r['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_dispatch_table(language):
    source = SOURCES[language]
    assert matches(source, language)
    assert matches(source.replace('Registry', 'Operations').replace('table', 'handlers'), language)


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('old,new', [
 ('table[requested]', 'other[requested]'),
 ('table[requested](data)', 'table[requested]'),
 ('table[key] = handler', 'table[key] = key'),
 ('table[key] = handler', 'table[handler] = handler'),
 ('table[requested]', 'table["constant"]'),
])
def test_dispatch_table_near_misses(language, old, new):
    assert not matches(SOURCES[language].replace(old, new), language)


def test_go_generic_conversion_is_not_an_indexed_call():
    source = 'package p; import "external"; func convert(value int) { _ = external.Kind[int](value) }'
    g = lower_source(source, 'go', 'example')
    assert not g.diagnostics
    assert not any(f.relation == 'CALLEE_VALUE' for f in g.facts)


def test_go_non_callable_map_is_not_disambiguated_as_dispatch():
    assert not matches(SOURCES['go'].replace('map[string]func(int)int', 'map[string]int'), 'go')


def test_dispatch_table_avoids_unrelated_method_parameter_cross_product():
    source = SOURCES['python'] + ''.join(
        f' def method{i}(self, a, b, c, d, e, f): self.field{i} = a\n'
        for i in range(150)
    )
    g = link_project([lower_source(source, 'python', 'large_registry.py')])
    registry = builtin_rules()
    result = execute_rules(g, [named_rule('architecture.dispatch-table', registry)],
                           QueryBudget(max_states=2000), registry=registry)
    assert result['complete'], result['outcomes']
    assert len(result['matches']) == 1
