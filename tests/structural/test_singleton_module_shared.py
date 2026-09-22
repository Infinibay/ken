"""Singleton ``module-shared``: an accessor exposes a shared initialized slot.

The variant is a published rule, so the test goes through the registry name
``singleton#module-shared`` rather than a private copy of the query.

Two shapes satisfy it, and the difference is which one carries the storage:

* **module binding** — Python/JS/TS/Go/Rust declare the slot at file scope and an
  exported accessor returns it;
* **function-local static** — C++ declares the slot inside the accessor with a
  ``static`` storage class, so it outlives the call.

The C++ case is why the storage class matters: ``Config get_config() { Config
instance = Config(); return instance; }`` is the same syntax minus ``static``
and is a fresh object per call, not a singleton. Without the specifier on the
slot there is nothing left to separate the two, so the rule requires it.

Go and Rust could not express either shape before this variant: a file-scope
``var``/``static`` was not lowered at all, so the read inside the accessor
invented a *callable-local* slot of the same spelling and the module never
declared the binding (IR 1.57).
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'singleton#module-shared'
LANGUAGES = ['python', 'javascript', 'typescript', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts',
              'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
# Only C++ reaches the storage through a function-local static; the other five
# bind it at module scope.
LOCAL_STATIC_LANGUAGES = ['cpp']


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'singleton')
    return next(v for v in rule.variants if v['id'] == 'module-shared')


def source(language, mode, names=None):
    names = names or {'type': 'Config', 'slot': 'shared', 'accessor': 'current'}
    type_name, slot, accessor = names['type'], names['slot'], names['accessor']
    if language == 'python':
        published = '_' + accessor if mode == 'unexported' else accessor
        slot_value = {'positive': f'{slot} = {type_name}()',
                      'unexported': f'{slot} = {type_name}()',
                      'fresh': f'{slot} = {type_name}()',
                      'uninitialized': f'{slot} = None'}[mode]
        body = (f'    return {type_name}()' if mode == 'fresh' else f'    return {slot}')
        return (f'class {type_name}:\n    pass\n\n{slot_value}\n\n'
                f'def {published}():\n{body}\n')
    if language == 'go':
        published = accessor[:1].upper() + accessor[1:] if mode != 'unexported' else accessor
        declared = (f'var {slot} {type_name}' if mode == 'uninitialized'
                    else f'var {slot} = {type_name}{{value: 1}}')
        body = (f'return {type_name}{{value: 1}}' if mode == 'fresh' else f'return {slot}')
        return (f'package singleton\n\ntype {type_name} struct{{ value int }}\n\n'
                f'{declared}\n\nfunc {published}() {type_name} {{\n\t{body}\n}}\n')
    if language == 'rust':
        # A Rust ``static`` always carries an initializer, so the missing
        # initialization negative has no Rust spelling and is not built for it.
        published = 'pub ' if mode != 'unexported' else ''
        body = (f'{type_name} {{ value: 1 }}' if mode == 'fresh' else f'&{slot.upper()}')
        returns = type_name if mode == 'fresh' else f"&'static {type_name}"
        return (f'pub struct {type_name} {{ pub value: i32 }}\n\n'
                f'static {slot.upper()}: {type_name} = {type_name} {{ value: 1 }};\n\n'
                f'{published}fn {accessor}() -> {returns} {{\n    {body}\n}}\n')
    if language == 'cpp':
        class_specifier = 'static ' if mode != 'plain-local' else ''
        body = (f'{type_name} {{ 1 }}' if mode == 'fresh' else slot)
        returns = type_name if mode == 'fresh' else f'{type_name}&'
        return (f'struct {type_name} {{ int value; }};\n\n'
                f'{returns} {accessor}() {{\n'
                f'    {class_specifier}{type_name} {slot} = {type_name}();\n'
                f'    return {body};\n}}\n')
    annotation = ': number' if language == 'typescript' else ''
    prefix = '' if mode == 'unexported' else 'export '
    slot_value = {'positive': f'const {slot} = new {type_name}();',
                  'unexported': f'const {slot} = new {type_name}();',
                  'fresh': f'const {slot} = new {type_name}();',
                  'uninitialized': f'const {slot} = null;'}[mode]
    body = f'return new {type_name}();' if mode == 'fresh' else f'return {slot};'
    return (f'class {type_name} {{ value{annotation} = 1; }}\n'
            f'{slot_value}\n'
            f'{prefix}function {accessor}(){annotation} {{ {body} }}\n')


def detect(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'singleton.{EXTENSIONS[language]}')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_shared_initialized_slot_exposed_by_an_accessor_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    bindings = matches[0]['bindings']
    # The shared role is the singleton's own type, matching lazy-guarded and
    # eager-shared, so the three variants agree on what ``$unit`` names.
    assert '/CLASS:' in bindings['$unit']
    assert bindings['$module'].endswith(f'singleton.{EXTENSIONS[language]}::module')
    assert bindings['$storage'] != bindings['$creation']
    assert bindings['$accessor'] != bindings['$creation']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    renamed = {'type': 'Registry', 'slot': 'only', 'accessor': 'acquire'}
    assert detect(language, 'positive', names=renamed)


@pytest.mark.parametrize('language', LANGUAGES)
def test_accessor_returning_a_fresh_construction_is_rejected(language):
    assert not detect(language, 'fresh')


@pytest.mark.parametrize('language', [l for l in LANGUAGES if l not in LOCAL_STATIC_LANGUAGES])
def test_non_public_accessor_is_rejected(language):
    assert not detect(language, 'unexported')


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript', 'go'])
def test_slot_not_initialized_from_a_construction_is_rejected(language):
    assert not detect(language, 'uninitialized')


def test_the_storage_class_is_what_admits_the_function_local_shape():
    """C++ reaches the storage only through ``static``; the plain local is not it."""
    assert detect('cpp', 'positive')
    assert not detect('cpp', 'plain-local')


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'module_decl $module' in row['query'] and 'exported: true' in row['query']
    assert 'body { return $storage; }' in row['query']


@pytest.mark.parametrize('language,ext', [('go', 'go'), ('rust', 'rs')])
def test_file_scope_declaration_binds_at_module_scope(language, ext):
    """A file-scope slot is the module's binding, not a slot invented by a read.

    Before IR 1.57 the declaration was not lowered, so ``return slot`` inside the
    accessor could not resolve the name and created a *callable-local* storage of
    the same spelling: the module declared nothing and the write and the return
    pointed at different entities.
    """
    graph = link_project([lower_source(source(language, 'positive'), language,
                                       f'singleton.{ext}')])
    assert not graph.diagnostics, graph.diagnostics
    module = f'singleton.{ext}::module'
    storages = {e.id for e in graph.entities.values() if e.kind == 'STORAGE' and '/STORAGE:' in e.id
                and e.name in {'shared', 'SHARED'}}
    assert len(storages) == 1, storages
    storage = storages.pop()
    assert storage.startswith(module + '/STORAGE:'), storage
    declares = {(f.subject, f.object) for f in graph.facts if f.relation == 'DECLARES'}
    assert (module, storage) in declares
    # Exactly one write of that slot, and it is the construction.
    targets = [f for f in graph.facts if f.relation == 'ASSIGNMENT_TARGET' and f.object == storage]
    assert len(targets) == 1, targets


def test_cpp_function_local_static_is_marked_shared():
    """The slot entity carries ``static`` so a per-call local cannot pass for it."""
    for mode, expected in [('positive', True), ('plain-local', False)]:
        graph = link_project([lower_source(source('cpp', mode), 'cpp', 'singleton.cpp')])
        assert not graph.diagnostics, graph.diagnostics
        slots = [e for e in graph.entities.values() if e.kind == 'STORAGE' and e.name == 'shared']
        assert len(slots) == 1, slots
        assert bool(slots[0].attrs.get('static')) is expected, mode
