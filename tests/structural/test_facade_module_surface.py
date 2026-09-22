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
    """A module entry coordinates two explicit service types, not local helpers.

    The previous positive used two identity functions in the same module, a shape
    indistinguishable from ordinary function composition. Distinct service types
    now supply the architectural boundary asserted by this strict detector.
    """
    names = names or NAMES
    reader = _camel(names['reader']) + 'Subsystem'
    writer = _camel(names['writer']) + 'Subsystem'
    entry = names['entry']
    steps = {
        'positive': ['carried = source.read(key)', 'metric = 1 + 2', 'log(metric)', 'return sink.write(carried)'],
        'unexported': ['carried = source.read(key)', 'metric = 1 + 2', 'log(metric)', 'return sink.write(carried)'],
        'independent': ['return key'],
        'overwritten': ['carried = source.read(key)', 'carried = 0', 'return sink.write(carried)'],
        'reversed': ['carried = 0', 'result = sink.write(carried)', 'carried = source.read(key)', 'return result'],
        'no-handoff': ['source.read(key)', 'return sink.write(0)'],
    }[mode]
    if language == 'python':
        name = '_' + entry if mode == 'unexported' else entry
        return (f'class {reader}:\n    def read(self, key): return key\n'
                f'class {writer}:\n    def write(self, value): return value\n'
                f'def {name}(key):\n    source = {reader}()\n    sink = {writer}()\n'
                + '\n'.join('    ' + step for step in steps) + '\n')
    if language == 'go':
        name = _camel(entry) if mode != 'unexported' else entry
        body = []
        declared = set()
        for step in steps:
            step = step.replace('.read(', '.Read(').replace('.write(', '.Write(').replace('log(', 'println(')
            if ' = ' in step:
                variable = step.split(' = ')[0]
                if variable not in declared:
                    step = step.replace(' = ', ' := ', 1)
                    declared.add(variable)
            body.append(step)
        return (f'package facade\n\ntype {reader} struct{{}}\n'
                f'func ({reader}) Read(key int) int {{ return key }}\n'
                f'type {writer} struct{{}}\n'
                f'func ({writer}) Write(value int) int {{ return value }}\n'
                f'func {name}(key int) int {{\n source := {reader}{{}}\n sink := {writer}{{}}\n'
                + '\n'.join('    ' + step for step in body) + '\n}\n')
    if language == 'rust':
        published = '' if mode == 'unexported' else 'pub '
        body = []
        declared = set()
        for step in steps:
            if ' = ' in step:
                variable = step.split(' = ')[0]
                if variable not in declared:
                    step = 'let mut ' + step
                    declared.add(variable)
            body.append(step + ';')
        return (f'struct {reader} {{}}\nimpl {reader} {{ fn read(&self, key: i32) -> i32 {{ key }} }}\n'
                f'struct {writer} {{}}\nimpl {writer} {{ fn write(&self, value: i32) -> i32 {{ value }} }}\n'
                f'{published}fn {entry}(key: i32) -> i32 {{\n'
                f'    let source = {reader} {{}};\n    let sink = {writer} {{}};\n'
                + '\n'.join('    ' + step for step in body) + '\n}\n')
    annotation = ': number' if language == 'typescript' else ''
    prefix = '' if mode == 'unexported' else 'export '
    body = []
    declared = set()
    for step in steps:
        if ' = ' in step:
            variable = step.split(' = ')[0]
            if variable not in declared:
                step = 'let ' + step
                declared.add(variable)
        body.append(step + ';')
    return (f'class {reader} {{ read(key{annotation}){annotation} {{ return key; }} }}\n'
            f'class {writer} {{ write(value{annotation}){annotation} {{ return value; }} }}\n'
            f'{prefix}function {entry}(key{annotation}){annotation} {{\n'
            f'  const source = new {reader}();\n  const sink = new {writer}();\n'
            + '\n'.join('  ' + step for step in body) + '\n}\n')


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
    assert 'exported: true;' in row['query'] and 'module_decl $module' in row['query']
    assert 'edge ' not in row['query'] and 'walk ' not in row['query']

@pytest.mark.parametrize('mode', ['positive','same_module','overwritten'])
def test_module_boundary_is_resolved_to_distinct_owners(mode):
    units=[lower_source('export function read(key) { return key; }','javascript','reader.js'),
           lower_source('export function write(value) { return value; }','javascript','writer.js')]
    if mode=='same_module':
        units=[lower_source('export function read(key) { return key; } export function write(value) {return value;}','javascript','reader.js')]
    target='reader' if mode=='same_module' else 'writer'
    replacement='value = 7;' if mode=='overwritten' else ''
    units.append(lower_source(f'import {{read}} from "./reader"; import {{write}} from "./{target}"; export function run(key) {{let value=read(key); {replacement} return write(value);}}','javascript','entry.js'))
    graph=link_project(units)
    registry=builtin_rules()
    result=execute_rules(graph,[named_rule(RULE,registry)],registry=registry)
    assert result['complete'],result
    assert bool(result['matches']) is (mode=='positive'),result
