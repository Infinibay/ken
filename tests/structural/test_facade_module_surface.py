"""Facade ``module-surface``: an exported entry coordinating two subsystems.

The catalog contract (``test_catalog_ir_contracts``) forbids a query on a
``design`` variant: a pending row is visible metadata, not a silently enabled
query. So the validated query lives here until the row can be promoted, which
requires Go and Rust coverage (PLAN.md P1.6).

Coverage is python / javascript / typescript. Go and Rust are blocked by the
analysis language whitelist and that blocker is asserted, not hidden.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from ken.structural.semantic import link_project

LANGUAGES = ['python', 'javascript', 'typescript']
BLOCKED = ['go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'go': 'go', 'rust': 'rs'}
NAMES = {'reader': 'fetch', 'writer': 'store', 'entry': 'run'}

# The contract this variant will publish once its five languages are covered.
QUERY = '''query facade_module_surface {
 require $module IS MODULE;
 require $module EXPORT $entry;
 require $entry IS CALLABLE;
 require $entry HAS_CALL $producer;
 require $producer RESULT $produced;
 require $entry HAS_CALL $consumer;
 require $consumer ARGUMENT $argument;
 require $argument VALUE $input;
 path $produced VALUE_FLOW{0,3} $input as $flow;
 different $producer $consumer;
 emit $module, $entry, $producer, $consumer;
}'''


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'facade')
    return next(v for v in rule.variants if v['id'] == 'module-surface')


def source(language, mode, names=None):
    names = names or NAMES
    reader, writer = names['reader'], names['writer']
    entry = '_' + names['entry'] if mode == 'unexported' and language == 'python' else names['entry']
    body = {
        'positive': ['carried = {r}(key)', 'metric = 1 + 2', 'print(metric)', 'return {w}(carried)'],
        'unexported': ['carried = {r}(key)', 'metric = 1 + 2', 'print(metric)', 'return {w}(carried)'],
        'independent': ['return key'],
        'overwritten': ['carried = {r}(key)', 'carried = 0', 'return {w}(carried)'],
        'reversed': ['carried = 0', 'result = {w}(carried)', 'carried = {r}(key)', 'return result'],
        'no-handoff': ['{r}(key)', 'return {w}(0)'],
    }[mode]
    statements = [line.format(r=reader, w=writer) for line in body]
    if language == 'python':
        head = [f'def {reader}(key):', '    return key', '', f'def {writer}(value):', '    return value', '', f'def {entry}(key):']
        return '\n'.join(head + ['    ' + s for s in statements]) + '\n'
    if language == 'go':
        return (f'package facade\n\n'
                f'func {reader.title()}(key int) int {{ return key }}\n'
                f'func {writer.title()}(value int) int {{ return value }}\n\n'
                f'func {entry.title()}(key int) int {{\n'
                + '\n'.join('\t' + s + '' for s in statements) + '\n}\n')
    if language == 'rust':
        return (f'pub fn {reader}(key: i32) -> i32 {{ key }}\n'
                f'pub fn {writer}(value: i32) -> i32 {{ value }}\n\n'
                f'pub fn {entry}(key: i32) -> i32 {{\n'
                + '\n'.join('    let ' + s + ';' if s.startswith('carried =') else '    ' + s + ';'
                            for s in statements[:-1])
                + '\n    ' + statements[-1].replace('return ', '') + '\n}\n')
    annotation = ': number' if language == 'typescript' else ''
    prefix = '' if mode == 'unexported' else 'export '
    return (f'export function {reader}(key{annotation}){annotation} {{ return key; }}\n'
            f'export function {writer}(value{annotation}){annotation} {{ return value; }}\n'
            f'{prefix}function {entry}(key{annotation}){annotation} {{\n'
            + '\n'.join('  ' + s + ';' for s in statements) + '\n}\n')


def detect(language, mode, names=None, evidence_mode='strict'):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'facade.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    rule = SavedRule('facade#module-surface', QUERY)
    result = execute_rules(graph, [rule], registry=registry, evidence_mode=evidence_mode)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_exported_entry_coordinating_two_subsystems_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    bindings = matches[0]['bindings']
    # The entry is the exported module function, not a class field.
    assert bindings['$entry'].endswith('/CALLABLE:run@' + bindings['$entry'].rsplit('@', 1)[1])
    assert bindings['$producer'] != bindings['$consumer']
    assert bindings['$module'].endswith('facade.' + EXTENSIONS[language] + '::module')


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    renamed = {'reader': 'alpha', 'writer': 'beta', 'entry': 'gamma'}
    assert detect(language, 'positive', names=renamed)


@pytest.mark.parametrize('language', LANGUAGES)
def test_entry_that_is_not_public_is_rejected(language):
    assert not detect(language, 'unexported')


@pytest.mark.parametrize('language', LANGUAGES)
def test_public_entry_without_coordination_is_rejected(language):
    assert not detect(language, 'independent')


@pytest.mark.parametrize('language', LANGUAGES)
def test_result_overwritten_before_consumption_is_rejected(language):
    assert not detect(language, 'overwritten')


@pytest.mark.parametrize('language', LANGUAGES)
def test_consumption_before_production_is_rejected(language):
    assert not detect(language, 'reversed')


@pytest.mark.parametrize('language', LANGUAGES)
def test_consumer_receiving_a_constant_is_rejected(language):
    assert not detect(language, 'no-handoff')


def test_variant_still_declares_every_target_language():
    """Coverage may not be shrunk silently to make the row look finished."""
    row = variant()
    assert row['languages'] == ['python', 'javascript', 'typescript', 'go', 'rust']
    assert row['status'] == 'design'
    assert 'P1.6' in row['missing_capability']
    # The catalog contract refuses a query on a pending row, so the validated
    # contract above is deliberately not published yet.
    assert not row.get('query')


@pytest.mark.parametrize('language', BLOCKED)
def test_go_and_rust_are_blocked_by_the_analysis_language(language):
    """The remaining blocker is explicit: no provenance facts for Go or Rust."""
    graph = link_project([lower_source(source(language, 'positive'), language,
                                       f'facade.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    statuses = [f for f in graph.facts if f.relation == 'RETURN_FLOW_STATUS']
    assert statuses
    assert all(f.object == 'unsupported' and f.attrs.get('reason') == 'language' for f in statuses)
    # Export evidence is already available; only the value analysis is missing.
    exports = [f for f in graph.facts if f.relation == 'EXPORT']
    assert len(exports) == 3
    result = execute_rules(graph, [SavedRule('facade#module-surface', QUERY)],
                           registry=builtin_rules(), evidence_mode='strict')
    assert result['complete']
    assert not result['matches']
