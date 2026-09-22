"""Historical dialect-compatibility checks, not a specification of design patterns.

The executor is a shared relational kernel. These tests detect compiler/catalog
migration regressions; they do not independently establish design intent.
"""
import json
from pathlib import Path

import pytest

from ken.structural.rules import SavedRule, builtin_rules, query_registry, execute_rules
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from .test_catalog_ir_contracts import SOURCES, ENTRIES

FROZEN = Path(__file__).parent/'catalog_matrix/pre_kql2_catalog.json'


@pytest.fixture(scope='module')
def registries():
    old = [SavedRule(**r) for r in json.loads(FROZEN.read_text())['rules']]
    new = [r for r in builtin_rules() if r.source]
    return query_registry(old), query_registry(new)


def contract(result):
    return (sorted((tuple(sorted(m['bindings'].items())),m['status'],tuple(m['unknown'])) for m in result['matches']),
            result['complete'], result['unknown'])


@pytest.mark.parametrize('parent,language,source', SOURCES, ids=[name+'/'+language for name,language,_ in SOURCES])
def test_every_entry_against_frozen_query_on_multilingual_source(parent,language,source,registries):
    old,new = registries
    index = query_graph(link_project([lower_source(source,language,'fixture.'+language)]))
    names = [entry.name for entry in ENTRIES if entry.parent == parent and entry.name in old]
    for name in names:
        before = Executor(index,old,QueryBudget(timeout_ms=3000,max_states=100_000)).execute(old[name])
        after = Executor(index,new,QueryBudget(timeout_ms=3000,max_states=100_000)).execute(new[name])
        if name in {'composite','composite#recursive-nominal'} and language in {'python','java','typescript'}:
            # The authored BODY reports unresolved dispatch for the nominal
            # alternative on an interface-typed collection. The contractual
            # alternative still supplies the same confirmed match. The frozen
            # signature silently treated missing dispatch as a definite absence.
            assert contract(after)[:2] == contract(before)[:2]
            assert before['unknown'] == [] and after['unknown'] == ['source_body:unknown']
            continue
        if name in {'template-method','template-method#trait-default'}:
            # A trait selector excludes ordinary classes before testing its
            # behavior; the former generic type/count signature stayed open.
            assert contract(after)[:2] == contract(before)[:2]
            assert before['unknown'] == ['cardinality:open_world'] and after['unknown'] == []
            continue
        if name in {'abstract-factory','abstract-factory#structural-families','factory-method.client_flow'} and language in {'java','typescript'}:
            # BODY now discloses unresolved return/argument origins. No confirmed
            # match may be gained or lost by this reviewed evidence-only delta.
            assert contract(after)[:2] == contract(before)[:2]
            assert before['unknown'] == [] and after['unknown'] == ['source_body:unknown']
            continue
        if name == 'iterator.iterate_over' and language == 'typescript':
            # The fixture is a generator (`yield* values`), whose body the walk
            # analysis cannot certify: the authored BODY discloses
            # `source_body:unknown` where the frozen edge query stayed silent. No
            # confirmed match may be gained or lost by this reviewed evidence-only delta.
            assert contract(after)[:2] == contract(before)[:2]
            assert before['unknown'] == [] and after['unknown'] == ['source_body:unknown']
            continue
        if name == 'interpreter':
            # The migrated root alternative carries the counted form
            # (`at least 2 distinct $child { ... }`). On this single-child fixture the
            # child inventory cannot be closed, so the counted clause discloses
            # `cardinality:open_world` where the frozen edge/tally query stayed silent.
            # No confirmed match may be gained or lost by this evidence-only delta.
            assert contract(after)[:2] == contract(before)[:2]
            assert before['unknown'] == [] and after['unknown'] == ['cardinality:open_world']
            continue
        assert contract(after) == contract(before), (name,language,before,after)


def test_public_catalog_executes_without_legacy_query_parser(monkeypatch):
    from ken.structural import kenql
    def forbidden(*args,**kwargs):
        raise AssertionError('KQL 2 catalog entered the KenQL 1 parser')
    monkeypatch.setattr(kenql,'Parser',forbidden)
    rules = [r for r in builtin_rules() if r.source]
    index = query_graph(link_project([lower_source('class Empty:\n pass\n','python','empty.py')]))
    result=execute_rules(index,rules)
    assert result['complete'] and not result['matches']
    assert len(result['outcomes']) == 33


def test_every_published_query_is_native_kql2():
    rules=[r for r in builtin_rules() if r.source]
    entries=[item for r in rules for item in [r.to_dict(), *r.variants, *r.operations] if item.get('query')]
    assert len(rules) == 33
    # 154 entries at the dialect migration; KQL 2 variants were added later
    # (mediator#registered-colleagues, mediator#broadcast-colleagues,
    # observer#registered-listeners, builder#accumulated-state,
    # decorator#typed-delegator, decorator#untyped-delegator,
    # decorator#subclass-addition).
    assert len(entries) == 161
    assert all(item['query'].startswith('language "kql/2";') for item in entries)
