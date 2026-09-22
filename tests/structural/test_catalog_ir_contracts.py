"""Catalog ABI: every executable query plus source/query-view round trips.

This is exhaustive for registered roots/variants/operations, not proof of recall
for every variant. Real-source positives cover every GoF and modern root; child
queries are also executed on their parent's sources, even when they do not match.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import tomllib

import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, parse, query_graph
from ken.structural.model import FactIndex, IR
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project

from .gof_sources import JAVA, PYTHON, TYPESCRIPT
from .test_adapted_continuation import SOURCES as ADAPTED
from .test_cache_aside import SOURCES as CACHE_ASIDE
from .test_closure_ownership import WRAPPERS
from .test_dispatch_table import SOURCES as DISPATCH
from .test_exception_retry import SOURCES as RETRY
from .test_modern_patterns import SOURCES as INJECTION
from .test_queued_commands import source as queued_source
from .test_read_through_cache import source as read_through_source
from .test_subclass_factories import source as subclass_source
from .test_unit_of_work import source as work_source

RULES = tuple(rule for rule in builtin_rules() if rule.source)
BY_ID = {rule.id: rule for rule in RULES}
QUERIES = query_registry(list(RULES))


@dataclass(frozen=True)
class Entry:
    name: str
    parent: str
    kind: str


def entries():
    for rule in RULES:
        yield Entry(rule.id, rule.id, 'root')
        for variant in rule.variants:
            if variant['status'] == 'ready':
                yield Entry(rule.id + '#' + variant['id'], rule.id, 'variant')
        for operation in rule.operations:
            if operation['status'] == 'ready':
                yield Entry(rule.id + '.' + operation['id'], rule.id, 'operation')


ENTRIES = tuple(entries())


def source_cases():
    for language, examples in [('python', PYTHON), ('java', JAVA), ('typescript', TYPESCRIPT)]:
        for name, text in sorted(examples.items()):
            yield name, language, text
    modern = {
        'architecture.adapted-continuation-wrapper': ADAPTED['python'],
        'architecture.batch-work-queue': queued_source('python'),
        'architecture.cache-aside': CACHE_ASIDE['python'],
        'architecture.continuation-wrapper': WRAPPERS['python'],
        'architecture.dependency-injection': INJECTION['python'],
        'architecture.dispatch-table': DISPATCH['python'],
        'resilience.exception-retry': RETRY['python'],
        'architecture.read-through-cache': read_through_source('python'),
        'architecture.subclass-factory': subclass_source('python'),
        'persistence.unit-of-work': work_source('python'),
    }
    for name, text in modern.items():
        yield name, 'python', text


SOURCES = tuple(source_cases())


def roundtrip(graph):
    return IR.from_dict(json.loads(json.dumps(graph.to_dict())))


def stable_outcome(outcome):
    # Timings and internal visited-row counts need not survive index rebuilding.
    return {'matches': outcome['matches'], 'unknown': outcome['unknown'], 'complete': outcome['complete']}


@pytest.fixture(scope='module')
def inert_index():
    graph = link_project([lower_source('class CatalogSmoke:\n pass\n', 'python', 'inert.py')])
    assert not graph.diagnostics
    return query_graph(roundtrip(graph))


@pytest.mark.parametrize('rule', RULES, ids=lambda r: r.id)
def test_toml_root_ready_design_and_operation_availability(rule):
    document = tomllib.loads(Path(rule.source).read_text())
    assert document['id'] == rule.id
    assert document['query'] == rule.query
    assert document.get('variants', []) == rule.variants
    assert document.get('operations', []) == rule.operations
    assert document['query_language'] == 'kql/2'
    assert document['query'].lstrip().startswith('language "kql/2";')
    assert parse(document['query']).exports
    for section, separator in [('variants', '#'), ('operations', '.')]:
        declared = document.get(section, [])
        assert len({item['id'] for item in declared}) == len(declared)
        for item in declared:
            assert item['status'] in {'ready', 'design'}
            name = rule.id + separator + item['id']
            if item['status'] == 'ready':
                assert isinstance(item.get('query'), str) and item['query'].strip()
                assert parse(item['query']).exports
                assert name in QUERIES
            else:
                # A pending variant is visible metadata, not a silently enabled query.
                assert not item.get('query')
                assert name not in QUERIES
                if 'gof' in rule.collections:
                    assert 'gof.' + name not in QUERIES


def test_source_cases_cover_all_roots_and_entry_names_are_unique():
    assert len(ENTRIES) == len({entry.name for entry in ENTRIES})
    assert {name for name, _, _ in SOURCES} == set(BY_ID)
    assert len([r for r in RULES if 'gof' in r.collections]) == 23


@pytest.mark.parametrize('entry', ENTRIES, ids=lambda e: e.name)
def test_every_executable_query_validates_dependencies_and_runs_without_vacuous_matches(entry, inert_index):
    query = QUERIES[entry.name]
    # The real engine checks every dependency, export role, selector kind and
    # relation even when the first join has no rows.
    engine = Engine(inert_index, QUERIES)
    engine.validate(query)
    for dependency, roles in query.dependencies():
        assert dependency in QUERIES
        assert set(roles) <= set(QUERIES[dependency].exports)
        assert not dependency.startswith('legacy.gof.'), entry.name
    outcome = engine.execute(query)
    assert outcome['complete'], (entry.name, outcome)
    assert not outcome['unknown'], (entry.name, outcome)
    assert not outcome['matches'], (entry.name, outcome)


@pytest.mark.parametrize('name,language,text', SOURCES, ids=[f'{n}-{l}' for n, l, _ in SOURCES])
def test_root_and_children_preserve_matches_through_source_and_query_ir_roundtrips(name, language, text):
    graph = link_project([lower_source(text, language, f'{name}.{language}')])
    assert not graph.diagnostics
    original = query_graph(graph)
    source_restored = query_graph(roundtrip(graph))
    query_restored = query_graph(roundtrip(original.ir))
    assert original.ir.view == query_restored.ir.view == 'query'
    assert graph.view == 'source'
    names = [entry.name for entry in ENTRIES if entry.parent == name]
    if 'gof' in BY_ID[name].collections:
        names.append('gof.' + name)
    observed = {}
    for query_name in names:
        outcomes = [Engine(index, QUERIES).execute(QUERIES[query_name])
                    for index in (original, source_restored, query_restored)]
        assert all(out['complete'] for out in outcomes), (query_name, language, outcomes)
        assert stable_outcome(outcomes[0]) == stable_outcome(outcomes[1]) == stable_outcome(outcomes[2])
        observed[query_name] = outcomes[0]
    assert observed[name]['matches'], (name, language)
    if 'gof' in BY_ID[name].collections:
        raw = {json.dumps(match['bindings'], sort_keys=True) for match in observed[name]['matches']}
        canonical = {json.dumps(match['bindings'], sort_keys=True) for match in observed['gof.' + name]['matches']}
        assert raw == canonical, (name, language, raw, canonical)


def promoted_operation_cases():
    from . import test_algorithm_bridge as bridge
    from . import test_algorithm_builder as builder
    from . import test_algorithm_factory_method as factory
    from . import test_algorithm_strategy as strategy
    from . import test_algorithm_template_method as template
    from . import test_algorithm_singleton as singleton

    for language in ('python', 'java', 'typescript'):
        for positive in (True, False):
            text = factory.instrument(factory.SOURCES[language], language)
            if not positive:
                text = text.replace('consume(self.make())', 'consume(Product())').replace('consume(this.make())', 'consume(new Product())')
            yield 'factory-method.client_flow', language, positive, text, factory.CLIENT_QUERY
            text = builder.instrument(builder.SOURCES[language], language)
            if not positive:
                text = text.replace('Product(self.x, self.y)', 'Product(0, 0)').replace('Product(this.x,this.y)', 'Product(0,0)')
            yield 'builder.directed_state', language, positive, text, builder.DIRECTED_STATE_QUERY
            text = bridge.body(language, bridge.statements(language, 'positive' if positive else 'overwritten'))
            yield 'bridge.returned_primitive', language, positive, text, bridge.RETURNED_PRIMITIVE
            text = strategy.source(language, 'object', '' if positive else 'overwrite-result')
            yield 'strategy.consumed_policy', language, positive, text, strategy.CONSUMED_POLICY.query
            text = template.source(language, noise=True)
            if not positive:
                text = text.replace('self.second(self.first(key))', 'self.second(0)').replace('this.second(this.first(key))', 'this.second(0)')
            yield 'template-method.dependent_steps', language, positive, text, template.DEPENDENT_STEPS
    for language in ('java', 'typescript'):
        for positive in (True, False):
            yield 'singleton.observed_lazy_use', language, positive, singleton.scoped_source(language, correct_usage=positive), None


PROMOTED_CASES = tuple(promoted_operation_cases())


def match_contract(outcome):
    return sorted(json.dumps({'bindings': match['bindings'], 'status': match['status'],
                              'unknown': match.get('unknown', [])}, sort_keys=True)
                  for match in outcome['matches'])


@pytest.mark.parametrize('name,language,positive,text,reference', PROMOTED_CASES,
                         ids=[f'{name}-{language}-{"positive" if positive else "negative"}'
                              for name, language, positive, _, _ in PROMOTED_CASES])
def test_promoted_operations_equal_existing_algorithm_queries(name, language, positive, text, reference):
    if reference is None:
        from .test_algorithm_singleton import usages
        graph, matches = usages(text, language)
        previous = {'matches': matches, 'complete': True}
    else:
        graph = link_project([lower_source(text, language, 'promoted-operation')])
        assert not graph.diagnostics
        previous = Engine(query_graph(graph), QUERIES).execute(parse(reference))
    current = Engine(query_graph(roundtrip(graph)), QUERIES).execute(QUERIES[name])
    assert previous['complete'] and current['complete']
    assert bool(previous['matches']) == positive, (name, language, previous)
    if name in {'factory-method.client_flow','strategy.consumed_policy','template-method.dependent_steps'}:
        # Authored BODY exports Operation witnesses. Compare the exact same
        # owner and byte span against historical Call-entity witnesses, rather
        # than requiring the legacy entity namespace in the public language.
        operations = {(op.owner,op.start,op.end):op.id for op in graph.operations if op.kind == 'CALL'}
        identities = {entity.id:operations[(entity.attrs.get('owner'),entity.attrs.get('start_byte'),entity.attrs.get('end_byte'))]
                      for entity in graph.entities.values() if entity.kind == 'CALL'
                      and (entity.attrs.get('owner'),entity.attrs.get('start_byte'),entity.attrs.get('end_byte')) in operations}
        previous = {**previous,'matches':[{**match,'bindings':{key:identities.get(value,value)
                     for key,value in match['bindings'].items()}} for match in previous['matches']]}
    assert match_contract(current) == match_contract(previous), (name, language)


def original_operation_cases():
    from .test_eager_singleton import SOURCES as eager
    from .test_pattern_operations import SOURCES as iteration
    from .test_rust_derived_clone import SOURCE as clone
    yield 'command.retained_dispatch', 'python', PYTHON['command']
    yield 'iterator.iterate_over', 'python', iteration['python']
    yield 'prototype.derived_copy', 'rust', clone
    yield 'singleton.shared_instance', 'java', eager['java']
    yield 'singleton.lazy_instance', 'python', PYTHON['singleton']
    yield 'strategy.supplied_policy', 'python', PYTHON['strategy']
    yield 'architecture.batch-work-queue.drain', 'python', queued_source('python')
    yield 'architecture.read-through-cache.read_fill', 'python', read_through_source('python')
    yield 'persistence.unit-of-work.keyed_flush', 'python', work_source('python')


    from . import test_algorithm_adapter as adapter
    from . import test_algorithm_visitor as visitor
    from . import test_algorithm_decorator as decorator
    from . import test_algorithm_bridge as bridge
    from . import test_algorithm_command as command
    from . import test_algorithm_mediator as mediator
    from . import test_algorithm_observer as observer
    from . import test_algorithm_interpreter as interpreter
    from . import test_algorithm_state as state
    from . import test_algorithm_flyweight as flyweight
    from . import test_algorithm_proxy as proxy
    from . import test_algorithm_chain_of_responsibility as chain
    from . import test_algorithm_composite as composite
    from . import test_algorithm_iterator as cursor
    for language in ('python', 'java', 'typescript'):
        yield 'adapter.input_conversion', language, adapter.source(language)
        yield 'adapter.output_conversion', language, adapter.source(language)
        yield 'visitor.result_forwarding', language, visitor.source(language)
        yield 'decorator.result_forwarding', language, decorator.source(language, decorator.body(language))
        yield 'bridge.injected_returned_primitive', language, bridge.body(language, bridge.statements(language))
        yield 'command.captured_payload', language, command.with_payload(language)
        yield 'mediator.event_delivery', language, mediator.source(language)
        yield 'interpreter.binary_result', language, interpreter.source(language)
        yield 'state.event_transition', language, state.source(language)
        yield 'flyweight.stable_intrinsic', language, flyweight.source(language)
        yield 'proxy.single_guarded_dispatch', language, proxy.source(language, proxy.guarded(language))
        yield 'chain-of-responsibility.single_exclusive_handler', language, chain.source(language)
        yield 'composite.additive_aggregate', language, composite.instrument(composite.SOURCES[language], language)
        yield 'iterator.advancing_element', language, cursor.instrument(cursor.CURSORS[language], language)
    for language in observer.LANGUAGES:
        yield 'observer.event_delivery', language, observer.source(language)


ORIGINAL_OPERATIONS = tuple(original_operation_cases())


def test_every_public_operation_has_a_positive_integration_case():
    covered = {name for name, *_ in ORIGINAL_OPERATIONS} | {name for name, *_ in PROMOTED_CASES}
    assert covered == {entry.name for entry in ENTRIES if entry.kind == 'operation'}


@pytest.mark.parametrize('name,language,text', ORIGINAL_OPERATIONS, ids=[name for name, *_ in ORIGINAL_OPERATIONS])
def test_original_operations_survive_query_view_roundtrip(name, language, text):
    graph = link_project([lower_source(text, language, 'public-operation')])
    assert not graph.diagnostics
    index = query_graph(graph)
    before = Engine(index, QUERIES).execute(QUERIES[name])
    after = Engine(query_graph(roundtrip(index.ir)), QUERIES).execute(QUERIES[name])
    assert before['complete'] and after['complete'] and before['matches']
    assert match_contract(before) == match_contract(after)


def test_gof_roots_reach_every_ready_variant_without_enabling_design_variants():
    for rule in RULES:
        if 'gof' not in rule.collections:
            continue
        reachable = set()
        pending = [rule.id]
        while pending:
            for name, _ in QUERIES[pending.pop()].dependencies():
                if name not in reachable:
                    reachable.add(name)
                    pending.append(name)
        from ken.kql2.syntax import parse as parse_kql2
        ready = {parse_kql2(variant['query']).module + '.detect'
                 for variant in rule.variants if variant['status'] == 'ready'}
        planned = {rule.id + '#' + variant['id'] for variant in rule.variants if variant['status'] == 'design'}
        reached_patterns = {QUERIES[name].name for name in reachable}
        assert ready <= reached_patterns, (rule.id, ready - reached_patterns)
        assert not planned & QUERIES.keys(), (rule.id, planned & QUERIES.keys())
