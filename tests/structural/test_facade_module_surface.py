"""Facade ``module-surface``: an exported entry coordinating two subsystems.

The variant is a published rule, so the test goes through the registry name
``facade#module-surface`` rather than a private copy of the query.

Coverage is all five declared languages. Go and Rust were admitted in P1.6 after
measuring that the ownership constructs they add are refused, not guessed: Go
multiple assignment targets an expression list and Rust tuple destructuring or
reference writes are indirect, so both surface as refusals instead of invented
origins (see docs/structural-validation/gof-completion/go-rust-p16.md).
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

LANGUAGES = ['python', 'javascript', 'typescript', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'go': 'go', 'rust': 'rs'}
NAMES = {'reader': 'fetch', 'writer': 'store', 'entry': 'run'}
RULE = 'facade#module-surface'


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'facade')
    return next(v for v in rule.variants if v['id'] == 'module-surface')


def _camel(name):
    """Go only exports an identifier whose first letter is upper-case."""
    return name[:1].upper() + name[1:]


def source(language, mode, names=None):
    names = names or NAMES
    reader, writer = names['reader'], names['writer']
    entry = names['entry']
    steps = {
        'positive': ['carried = {r}(key)', 'metric = 1 + 2', 'log(metric)', 'return {w}(carried)'],
        'unexported': ['carried = {r}(key)', 'metric = 1 + 2', 'log(metric)', 'return {w}(carried)'],
        'independent': ['return key'],
        'overwritten': ['carried = {r}(key)', 'carried = 0', 'return {w}(carried)'],
        'reversed': ['carried = 0', 'result = {w}(carried)', 'carried = {r}(key)', 'return result'],
        'no-handoff': ['{r}(key)', 'return {w}(0)'],
    }[mode]
    steps = [s.format(r=reader, w=writer) for s in steps]
    if language == 'python':
        name = '_' + entry if mode == 'unexported' else entry
        head = [f'def {reader}(key):', '    return key', '', f'def {writer}(value):', '    return value',
                '', f'def {name}(key):']
        return '\n'.join(head + ['    ' + s for s in steps]) + '\n'
    if language == 'go':
        reader, writer = _camel(reader), _camel(writer)
        name = _camel(entry) if mode != 'unexported' else entry
        body = {'positive': ['carried := {r}(key)', 'metric := 1 + 2', 'println(metric)', 'return {w}(carried)'],
                'unexported': ['carried := {r}(key)', 'metric := 1 + 2', 'println(metric)', 'return {w}(carried)'],
                'independent': ['return key'],
                'overwritten': ['carried := {r}(key)', 'carried = 0', 'return {w}(carried)'],
                'reversed': ['carried := 0', 'result := {w}(carried)', 'carried = {r}(key)', 'return result'],
                'no-handoff': ['{r}(key)', 'return {w}(0)']}[mode]
        body = [s.format(r=reader, w=writer) for s in body]
        return (f'package facade\n\nfunc {reader}(key int) int {{ return key }}\n'
                f'func {writer}(value int) int {{ return value }}\n\n'
                f'func {name}(key int) int {{\n' + '\n'.join('\t' + s for s in body) + '\n}\n')
    if language == 'rust':
        name = entry
        published = '' if mode == 'unexported' else 'pub '
        body = {'positive': ['let carried = {r}(key);', 'let metric = 1 + 2;', 'log(metric);', '{w}(carried)'],
                'unexported': ['let carried = {r}(key);', 'let metric = 1 + 2;', 'log(metric);', '{w}(carried)'],
                'independent': ['key'],
                'overwritten': ['let mut carried = {r}(key);', 'carried = 0;', '{w}(carried)'],
                'reversed': ['let mut carried = 0;', 'let result = {w}(carried);', 'carried = {r}(key);', 'result'],
                'no-handoff': ['{r}(key);', '{w}(0)']}[mode]
        body = [s.format(r=reader, w=writer) for s in body]
        return (f'pub fn {reader}(key: i32) -> i32 {{ key }}\n'
                f'pub fn {writer}(value: i32) -> i32 {{ value }}\n\n'
                f'{published}fn {name}(key: i32) -> i32 {{\n' + '\n'.join('    ' + s for s in body) + '\n}\n')
    annotation = ': number' if language == 'typescript' else ''
    prefix = '' if mode == 'unexported' else 'export '
    body = [s + ';' for s in steps]
    return (f'export function {reader}(key{annotation}){annotation} {{ return key; }}\n'
            f'export function {writer}(value{annotation}){annotation} {{ return value; }}\n'
            f'{prefix}function {entry}(key{annotation}){annotation} {{\n'
            + '\n'.join('  ' + s for s in body) + '\n}\n')


def detect(language, mode, names=None, evidence_mode='strict'):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'facade.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode=evidence_mode)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_exported_entry_coordinating_two_subsystems_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role is the entry itself: a class for object-surface, a module
    # function here. The declaration is not used as the detector.
    assert '/CALLABLE:' in bindings['$unit']
    assert bindings['$producer'] != bindings['$consumer']
    assert bindings['$module'].endswith(f'facade.{EXTENSIONS[language]}::module')


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    renamed = {'reader': 'Alpha', 'writer': 'Beta', 'entry': 'Gamma'}
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


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'EXPORT' in row['query'] and 'IS MODULE' in row['query']
