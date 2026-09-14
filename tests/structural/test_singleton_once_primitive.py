"""Singleton ``once-primitive``: a cell API retains the value an accessor returns.

The variant is a published rule, so the tests go through the registry name
``singleton#once-primitive`` rather than a private copy of the query.

Five languages reach an exactly-once cell through five different standard APIs,
and each one hands the retained value back differently:

* **Go** — ``sync.Once.Do`` stores the value in a module slot that the accessor
  returns, so the guard and the value are two entities;
* **C++** — ``std::call_once`` takes the ``std::once_flag`` as its *first
  argument* (it is a free function, not a method) and publishes a file-scope slot;
* **Rust** — ``OnceLock::get_or_init`` takes the thunk on the cell and the accessor
  returns the *call*, because the cell itself holds the value;
* **Java** — ``AtomicReference::updateAndGet`` is the JDK's compare-and-set
  compute-once idiom, and the accessor returns the call;
* **C#** — ``Lazy<T>`` is built *from* the thunk, so the cell is the assignment
  target of a construction call and the accessor reads the ``Value`` member.

The shared-scope clause is what separates the shared cell from a per-invocation
one. Go has no dedicated syntax for that: a ``var`` inside a callable is a new
binding even when the file declares the same spelling, and before IR 1.67 the
declaration was not lowered, so a guard created fresh on every call resolved to
the file-scope slot (see
``test_a_function_local_var_is_not_the_module_slot``).
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'singleton#once-primitive'
ROOT = 'singleton'
LANGUAGES = ['java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'java': 'java', 'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
DEFAULT_NAMES = {'type': 'Config', 'slot': 'shared', 'cell': 'guard', 'accessor': 'current'}
RENAMED_NAMES = {'type': 'Registry', 'slot': 'only', 'cell': 'latch', 'accessor': 'acquire'}

# Modes that must not satisfy the variant. Go and C++ distinguish three locals:
# the guard may be the only declaration of its spelling, it may shadow a file-scope
# guard of the same spelling, or the payload slot may be the per-call one.
NEGATIVES = {
    'go': ['local-guard', 'shadowed-guard', 'local-slot', 'crossed', 'fresh'],
    'cpp': ['local-guard', 'shadowed-guard', 'local-slot', 'crossed', 'fresh'],
    'rust': ['local', 'crossed', 'fresh'],
    'csharp': ['local', 'crossed', 'fresh'],
    'java': ['local', 'crossed', 'fresh'],
}
# Rust cannot reassign a ``static``, so the reset counterexample has no Rust
# spelling and is only built for the other four.
RESET_LANGUAGES = ['java', 'csharp', 'cpp', 'go']


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'once-primitive')


def source(language, mode, names=None):
    names = names or DEFAULT_NAMES
    type_name, slot, cell, accessor = (names['type'], names['slot'],
                                       names['cell'], names['accessor'])
    if language == 'go':
        declarations = {
            'positive': f'var {slot} *{type_name}\nvar {cell} sync.Once',
            'local-guard': f'var {slot} *{type_name}',
            'shadowed-guard': f'var {slot} *{type_name}\nvar {cell} sync.Once',
            'local-slot': f'var {cell} sync.Once',
            'crossed': f'var {slot} *{type_name}\nvar other *{type_name}\nvar {cell} sync.Once',
            'fresh': f'var {cell} sync.Once',
            'reset': f'var {slot} *{type_name}\nvar {cell} sync.Once',
        }
        bodies = {
            'positive': (f'\t{cell}.Do(func() {{\n\t\t{slot} = &{type_name}{{value: 1}}\n\t}})\n'
                         f'\treturn {slot}'),
            'local-guard': (f'\tvar {cell} sync.Once\n\t{cell}.Do(func() {{\n'
                            f'\t\t{slot} = &{type_name}{{value: 1}}\n\t}})\n\treturn {slot}'),
            'shadowed-guard': (f'\tvar {cell} sync.Once\n\t{cell}.Do(func() {{\n'
                               f'\t\t{slot} = &{type_name}{{value: 1}}\n\t}})\n\treturn {slot}'),
            'local-slot': (f'\tvar {slot} *{type_name}\n\t{cell}.Do(func() {{\n'
                           f'\t\t{slot} = &{type_name}{{value: 1}}\n\t}})\n\treturn {slot}'),
            'crossed': (f'\t{cell}.Do(func() {{\n\t\tother = &{type_name}{{value: 1}}\n\t}})\n'
                        f'\treturn {slot}'),
            'fresh': f'\t{cell}.Do(func() {{}})\n\treturn &{type_name}{{value: 1}}',
            'reset': (f'\t{cell}.Do(func() {{\n\t\t{slot} = &{type_name}{{value: 1}}\n\t}})\n'
                      f'\t{slot} = &{type_name}{{value: 2}}\n\treturn {slot}'),
        }
        return (f'package singleton\n\nimport "sync"\n\n'
                f'type {type_name} struct{{ value int }}\n\n'
                f'{declarations[mode]}\n\n'
                f'func {accessor}() *{type_name} {{\n{bodies[mode]}\n}}\n')
    if language == 'cpp':
        declarations = {
            'positive': f'static {type_name}* {slot} = nullptr;\nstatic std::once_flag {cell};',
            'local-guard': f'static {type_name}* {slot} = nullptr;',
            'shadowed-guard': f'static {type_name}* {slot} = nullptr;\nstatic std::once_flag {cell};',
            'local-slot': f'static std::once_flag {cell};',
            'crossed': (f'static {type_name}* {slot} = nullptr;\n'
                        f'static {type_name}* other = nullptr;\nstatic std::once_flag {cell};'),
            'fresh': f'static std::once_flag {cell};',
            'reset': f'static {type_name}* {slot} = nullptr;\nstatic std::once_flag {cell};',
        }
        bodies = {
            'positive': (f'    std::call_once({cell}, []() {{ {slot} = new {type_name}(); }});\n'
                         f'    return {slot};'),
            'local-guard': (f'    std::once_flag {cell};\n'
                            f'    std::call_once({cell}, []() {{ {slot} = new {type_name}(); }});\n'
                            f'    return {slot};'),
            'shadowed-guard': (f'    std::once_flag {cell};\n'
                               f'    std::call_once({cell}, []() {{ {slot} = new {type_name}(); }});\n'
                               f'    return {slot};'),
            'local-slot': (f'    {type_name}* {slot} = nullptr;\n'
                           f'    std::call_once({cell}, [&]() {{ {slot} = new {type_name}(); }});\n'
                           f'    return {slot};'),
            'crossed': (f'    std::call_once({cell}, []() {{ other = new {type_name}(); }});\n'
                        f'    return {slot};'),
            'fresh': (f'    std::call_once({cell}, []() {{}});\n'
                      f'    return new {type_name}();'),
            'reset': (f'    std::call_once({cell}, []() {{ {slot} = new {type_name}(); }});\n'
                      f'    {slot} = new {type_name}();\n    return {slot};'),
        }
        return (f'#include <mutex>\n\n'
                f'class {type_name} {{ public: int value; }};\n\n'
                f'{declarations[mode]}\n\n'
                f'{type_name}* {accessor}() {{\n{bodies[mode]}\n}}\n')
    if language == 'rust':
        declarations = {
            'positive': f'static {cell}: OnceLock<{type_name}> = OnceLock::new();',
            'local': '',
            'crossed': (f'static {cell}: OnceLock<{type_name}> = OnceLock::new();\n'
                        f'static other: OnceLock<{type_name}> = OnceLock::new();'),
            'fresh': f'static {cell}: OnceLock<{type_name}> = OnceLock::new();',
        }
        bodies = {
            'positive': f'    {cell}.get_or_init(|| {type_name} {{ value: 1 }})',
            'local': (f'    let {cell}: OnceLock<{type_name}> = OnceLock::new();\n'
                      f'    {cell}.get_or_init(|| {type_name} {{ value: 1 }})'),
            'crossed': (f'    other.get_or_init(|| {type_name} {{ value: 1 }});\n'
                        f'    {cell}.get()'),
            'fresh': (f'    {cell}.get_or_init(|| {type_name} {{ value: 1 }});\n'
                      f'    {type_name} {{ value: 2 }}'),
        }
        return (f'use std::sync::OnceLock;\n\n'
                f'pub struct {type_name} {{ pub value: i32 }}\n\n'
                f'{declarations[mode]}\n\n'
                f'pub fn {accessor}() -> &\'static {type_name} {{\n{bodies[mode]}\n}}\n')
    if language == 'csharp':
        declarations = {
            'positive': (f'    private static readonly Lazy<{type_name}> {cell} = '
                         f'new Lazy<{type_name}>(() => new {type_name}());'),
            'local': '',
            'crossed': (f'    private static readonly Lazy<{type_name}> {cell} = '
                        f'new Lazy<{type_name}>();\n'
                        f'    private static readonly Lazy<{type_name}> other = '
                        f'new Lazy<{type_name}>(() => new {type_name}());'),
            'fresh': (f'    private static readonly Lazy<{type_name}> {cell} = '
                      f'new Lazy<{type_name}>(() => new {type_name}());'),
            'reset': (f'    private static readonly Lazy<{type_name}> {cell} = '
                      f'new Lazy<{type_name}>(() => new {type_name}());'),
        }
        bodies = {
            'positive': f'return {cell}.Value;',
            'local': (f'var {cell} = new Lazy<{type_name}>(() => new {type_name}()); '
                      f'return {cell}.Value;'),
            'crossed': f'return {cell}.Value;',
            'fresh': f'{cell}.Value.ToString(); return new {type_name}();',
            'reset': (f'{cell} = new Lazy<{type_name}>(() => new {type_name}()); '
                      f'return {cell}.Value;'),
        }
        return (f'using System;\n\n'
                f'public class {type_name} {{ public int Value = 1; }}\n\n'
                f'public static class Holder {{\n{declarations[mode]}\n'
                f'    public static {type_name} {accessor}() {{ {bodies[mode]} }}\n}}\n')
    if language == 'java':
        declarations = {
            'positive': (f'    private static final AtomicReference<{type_name}> {cell} = '
                         f'new AtomicReference<>(null);'),
            'local': '',
            'crossed': (f'    private static final AtomicReference<{type_name}> {cell} = '
                        f'new AtomicReference<>(null);\n'
                        f'    private static final AtomicReference<{type_name}> other = '
                        f'new AtomicReference<>(null);'),
            'fresh': (f'    private static final AtomicReference<{type_name}> {cell} = '
                      f'new AtomicReference<>(null);'),
            'reset': (f'    private static final AtomicReference<{type_name}> {cell} = '
                      f'new AtomicReference<>(null);'),
        }
        returned = f'{cell}.updateAndGet(prev -> prev != null ? prev : new {type_name}())'
        bodies = {
            'positive': f'return {returned};',
            'local': (f'AtomicReference<{type_name}> {cell} = new AtomicReference<>(null);\n'
                      f'        return {returned};'),
            'crossed': (f'other.updateAndGet(prev -> prev != null ? prev : new {type_name}());\n'
                        f'        return {cell}.get();'),
            'fresh': (f'{returned};\n        return new {type_name}();'),
            'reset': (f'{cell}.set(new {type_name}());\n        return {returned};'),
        }
        return (f'import java.util.concurrent.atomic.AtomicReference;\n\n'
                f'class {type_name} {{ int value = 1; }}\n\n'
                f'public final class Holder {{\n{declarations[mode]}\n'
                f'    public static {type_name} {accessor}() {{\n        {bodies[mode]}\n    }}\n}}\n')
    raise AssertionError(language)


def build(language, mode, names=None):
    text = source(language, mode, names)
    graph = link_project([lower_source(text, language,
                                       f'singleton.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, (language, mode, graph.diagnostics)
    return graph


def detect(language, mode, names=None, rule=RULE):
    graph = build(language, mode, names)
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_once_cell_accessor_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role is the retained type, so the four singleton variants agree
    # on what ``$unit`` names.
    assert '/CLASS:' in bindings['$unit']
    assert bindings['$cell'] != bindings['$accessor']
    assert bindings['$thunk'] != bindings['$construction']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    assert detect(language, 'positive', names=RENAMED_NAMES)


@pytest.mark.parametrize('language,mode', [(language, mode) for language, modes in NEGATIVES.items()
                                           for mode in modes])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', RESET_LANGUAGES)
def test_a_later_write_of_the_retained_value_is_not_yet_rejected(language):
    """Boundary: the variant proves initialization, not immutability afterwards.

    For Go and C++ the reset writes the payload slot again and is not modelled;
    for Java and C# the cell is re-assigned. The evidence is the same size as the
    positive's, so the match is still reported. This test pins that boundary
    instead of claiming a guarantee the catalog contract does not make.
    """
    assert detect(language, 'reset')


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_once_cell(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert matches, language


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'ALLOCATES_TYPE' in row['query']
    assert 'RETURNS_CALL' in row['query'] and 'RETURNS_STORAGE' in row['query']
    assert 'DECLARES $cell' in row['query'] and 'DECLARES $slot' in row['query']


def test_a_function_local_var_is_not_the_module_slot():
    """A Go ``var`` inside a callable binds a new name, even beside a file one.

    Before IR 1.67 a function-local ``var`` was not lowered, so ``once.Do``
    inside the accessor resolved the spelling outward to the *module* slot and a
    guard created fresh on every call was indistinguishable from the shared one.
    ``shadowed-guard`` is the shape that exposes it: the file declares ``guard``
    as well, so the two write sets would otherwise merge into one entity.
    """
    module = 'singleton.go::module'
    name = DEFAULT_NAMES['cell']
    for mode, expected in [('positive', 1), ('shadowed-guard', 2)]:
        graph = build('go', mode)
        guards = sorted(e.id for e in graph.entities.values()
                        if e.kind == 'STORAGE' and e.name == name)
        assert len(guards) == expected, (mode, guards)
        shared = next(g for g in guards if g.startswith(f'{module}/STORAGE:'))
        declares = {(f.subject, f.object) for f in graph.facts if f.relation == 'DECLARES'}
        assert (module, shared) in declares, mode
        for local in (g for g in guards if g not in {shared}):
            assert local.startswith(f'{module}/CALLABLE:'), (mode, local)
            assert (module, local) not in declares, (mode, local)

