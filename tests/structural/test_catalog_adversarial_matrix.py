"""Every advertised variant/language gets both oracles and robustness contrasts.

Known disagreements are exact case IDs with reviewed causes. Parser failures,
invalid queries and budget exhaustion can never be hidden by those expectations.
Fixing a known disagreement fails with XPASS until its ledger entry is removed.
"""
from collections import Counter
from functools import lru_cache
import json

import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project

from .catalog_matrix_support import DIRECTORY, FAMILIES, directed_cases, matrix_cases

MATRIX = matrix_cases()
CASES = (*MATRIX, *directed_cases())
LEDGER = json.loads((DIRECTORY / 'known_failures.json').read_text())


@pytest.fixture(scope='module')
def registry():
    return query_registry(builtin_rules())


@lru_cache(maxsize=32)
def indexed_source(language, source):
    graph = link_project([lower_source(source, language, 'catalog-matrix.' + language)])
    return graph.diagnostics, query_graph(graph)


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.id)
def test_catalog_semantic_oracle(case, registry):
    if case.language == 'python':
        compile(case.source, '<catalog-matrix>', 'exec')  # Syntax check only; never execute.
    diagnostics, index = indexed_source(case.language, case.source)
    assert not diagnostics, diagnostics
    engine = Engine(index, registry, QueryBudget(max_matches=200, max_rows=500000,
                                               max_states=100000, timeout_ms=3000), 'strict')
    result = engine.execute(registry[case.target])
    assert result['complete'], result
    actual = bool(result['matches'])
    known = LEDGER['cases'].get(case.id)
    if known:
        issue = LEDGER['issues'][known['issue']]
        if actual == case.expected:
            pytest.fail(f'XPASS: {case.id} is fixed; remove its known-failure entry. {issue["title"]}')
        observed = 'FP' if actual else 'FN'
        assert observed == known['observed'], (known, result)
        pytest.xfail(f'{known["issue"]}: {issue["cause_and_fix"]}')
    assert actual is case.expected, (case.id, case.reason, result)


def test_catalog_language_inventory_has_no_silent_gaps():
    manifest = json.loads((DIRECTORY / 'seeds.json').read_text())
    required = manifest['required']
    expected_targets = set()
    for rule in builtin_rules():
        if not rule.source:
            continue
        if not rule.variants:
            expected_targets.add(rule.id)
            assert required.get(rule.id), f'Root without variants needs an explicit language scope: {rule.id}'
        for variant in rule.variants:
            if variant['status'] != 'ready':
                continue
            target = rule.id + '#' + variant['id']
            expected_targets.add(target)
            assert required.get(target), target
            if variant.get('languages'):
                assert set(required[target]) == set(variant['languages']), target
    assert set(required) == expected_targets
    actual = Counter((c.target, c.language, c.family) for c in MATRIX)
    expected = {(t, language, family) for t, languages in required.items()
                for language in languages for family in FAMILIES}
    assert set(actual) == expected
    assert all(count == 1 for count in actual.values())


def test_ledger_is_exact_and_every_failure_has_a_reviewed_cause():
    ids = {c.id for c in CASES}
    assert len(ids) == len(CASES)
    assert set(LEDGER['cases']) <= ids
    for name, failure in LEDGER['cases'].items():
        assert failure['observed'] in {'FP', 'FN'}, name
        assert LEDGER['issues'][failure['issue']]['cause_and_fix'], name
        case = next(c for c in CASES if c.id == name)
        assert case.expected is (failure['observed'] == 'FN')


def test_interleaving_cases_change_the_source_and_have_unique_identities():
    originals = {(c.target, c.language): c.source for c in MATRIX if c.family == 'canonical'}
    for case in MATRIX:
        if case.family.startswith('noise-'):
            assert case.source != originals[case.target, case.language], case.id
