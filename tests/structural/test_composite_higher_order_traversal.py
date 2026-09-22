"""Composite ``higher-order-traversal``: iterating children feeds the returned total.

The variant is a published rule, so the tests go through the registry name
``composite#higher-order-traversal`` rather than a private copy of the query.

The shape is the one the design table lists for every language: the component's
operation walks its own child collection, invokes the *same-named* operation on
the iterated element, and the element's result accumulates into the local the
operation returns. That is what separates it from ``recursive-nominal``, which
proves the uniform recursive call but not what happens to the child's result.

Two boundaries are pinned rather than claimed:

* **re-assigned element** — the element binding may be written again inside the
  loop (``child = self.children[0]``) and the query still matches: the update is
  not modelled as invalidating the iterated value. Go, C++ and Rust have no
  per-callable write inventory at all, and in all eight languages the ``+=`` that
  publishes the total marks the callable ``binding-writes/1`` *unsupported*
  (``indirect-write``), so there is no count to require.
* **callback form** — ``children.reduce((acc, child) => ..., 0)`` honestly
  expresses the same traversal, but the IR emits no ``ITERATED_CALL`` for it: the
  callback's element parameter is not linked to the collection. This is the
  ``closure_capture`` half the variant row declares and it is not implemented.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'composite#higher-order-traversal'
ROOT = 'composite'
LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'python': 'py', 'javascript': 'js', 'typescript': 'ts', 'java': 'java',
              'csharp': 'cs', 'cpp': 'cpp', 'go': 'go', 'rust': 'rs'}
DEFAULT_NAMES = {'type': 'Component', 'unit': 'Subject', 'field': 'children',
                 'operation': 'count', 'accumulator': 'total', 'element': 'child'}
RENAMED_NAMES = {'type': 'Shape', 'unit': 'Group', 'field': 'members',
                 'operation': 'count', 'accumulator': 'sum', 'element': 'item'}

NEGATIVES = ['discarded', 'other-accumulator', 'foreign-operation',
             'no-iteration', 'local-collection']
BOUNDARY_MODES = ['reassigned-element']
# Only the three languages whose canonical fold is a library call are used to
# pin the unimplemented callback shape.
CALLBACK_LANGUAGES = ['python', 'javascript', 'typescript']

# How one language spells "the component's own child collection" and "its first
# element". Keeping them here is what lets the eight templates below stay short.
FIELD = {'python': 'self.{field}', 'javascript': 'this.{field}', 'typescript': 'this.{field}',
         'java': '{field}', 'csharp': '{field}', 'cpp': '{field}',
         'go': 's.{field}', 'rust': 'self.{field}'}
FIRST = {'python': 'self.{field}[0]', 'javascript': 'this.{field}[0]',
         'typescript': 'this.{field}[0]', 'java': '{field}.get(0)', 'csharp': '{field}[0]',
         'cpp': '{field}[0]', 'go': 's.{field}[0]', 'rust': 'self.{field}[0]'}
CALL = {'cpp': '{element}->{operation}(ctx)'}


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'higher-order-traversal')


def plans(language, mode, names):
    """The pre-loop statements, the loop body and whether a loop runs at all."""
    n = names
    field_expr = FIELD[language].format(field=n['field'])
    first = FIRST[language].format(field=n['field'])
    child = CALL.get(language, '{element}.{operation}(ctx)').format(element=n['element'],
                                                                    operation=n['operation'])
    accumulator, element = n['accumulator'], n['element']
    if mode == 'positive':
        return [f'{accumulator} = 0'], [f'{accumulator} += {child}'], field_expr
    if mode == 'discarded':
        return [f'{accumulator} = 0'], [child], field_expr
    if mode == 'other-accumulator':
        return [f'{accumulator} = 0', 'other = 0'], [f'other += {child}'], field_expr
    if mode == 'foreign-operation':
        return [f'{accumulator} = 0'], [f'{accumulator} += {element}.other(ctx)'], field_expr
    if mode == 'no-iteration':
        return [f'{accumulator} = 0'], [f'{accumulator} += {child}'], None
    if mode == 'local-collection':
        return [f'{accumulator} = 0', f'items = {field_expr}'], [f'{accumulator} += {child}'], 'items'
    if mode == 'reassigned-element':
        return ([f'{accumulator} = 0'],
                [f'{element} = {first}', f'{accumulator} += {child}'], field_expr)
    raise AssertionError(mode)


def source(language, mode, names=None):
    n = names or DEFAULT_NAMES
    type_name, unit, field = n['type'], n['unit'], n['field']
    operation, accumulator, element = n['operation'], n['accumulator'], n['element']
    prelude, body, loop = plans(language, mode, n)
    first = FIRST[language].format(field=field)
    direct = CALL.get(language, '{element}.{operation}(ctx)').format(element=first,
                                                                     operation=operation)
    if language == 'python':
        statements = list(prelude)
        if loop is None:
            statements.append(f'{accumulator} += {direct}')
        else:
            inner = '\n'.join(f'            {line}' for line in body)
            statements.append(f'for {element} in {loop}:\n{inner}')
        body_text = '\n'.join(f'        {line}' for line in statements)
        return (f'class {type_name}:\n'
                f'    def {operation}(self, ctx):\n        return 0\n\n'
                f'class {unit}({type_name}):\n'
                f'    def __init__(self, {field}):\n        self.{field} = {field}\n\n'
                f'    def {operation}(self, ctx):\n{body_text}\n'
                f'        return {accumulator}\n')
    if language in {'javascript', 'typescript'}:
        annotation = ': number' if language == 'typescript' else ''
        typed = ': Ctx' if language == 'typescript' else ''
        param_type = f': {type_name}[]' if language == 'typescript' else ''
        declared = f'  {field}: {type_name}[];\n' if language == 'typescript' else ''
        ctx_class = 'class Ctx {}\n' if language == 'typescript' else ''
        statements = [f'let {line};' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct};')
        else:
            inner = ' '.join(f'{line};' for line in body)
            statements.append(f'for (const {element} of {loop}) {{ {inner} }}')
        body_text = '\n    '.join(statements)
        return (f'{ctx_class}'
                f'class {type_name} {{ {operation}(ctx{typed}){annotation} {{ return 0; }} }}\n'
                f'class {unit} extends {type_name} {{\n{declared}'
                f'  constructor({field}{param_type}) {{ super(); this.{field} = {field}; }}\n'
                f'  {operation}(ctx{typed}){annotation} {{\n    {body_text}\n'
                f'    return {accumulator};\n  }}\n}}\n')
    if language == 'java':
        statements = [f'int {line};' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct};')
        else:
            inner = ' '.join(f'{line};' for line in body)
            statements.append(f'for ({type_name} {element} : {loop}) {{ {inner} }}')
        body_text = '\n        '.join(statements)
        return (f'import java.util.List;\n'
                f'class Ctx {{}}\n'
                f'abstract class {type_name} {{ abstract int {operation}(Ctx ctx); }}\n'
                f'class {unit} extends {type_name} {{\n'
                f'    private final List<{type_name}> {field};\n'
                f'    {unit}(List<{type_name}> {field}) {{ this.{field} = {field}; }}\n'
                f'    int {operation}(Ctx ctx) {{\n        {body_text}\n'
                f'        return {accumulator};\n    }}\n}}\n')
    if language == 'csharp':
        statements = [f'int {line};' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct};')
        else:
            inner = ' '.join(f'{line};' for line in body)
            statements.append(f'foreach ({type_name} {element} in {loop}) {{ {inner} }}')
        body_text = '\n        '.join(statements)
        return (f'using System.Collections.Generic;\n'
                f'class Ctx {{}}\n'
                f'abstract class {type_name} {{ public abstract int {operation}(Ctx ctx); }}\n'
                f'class {unit} : {type_name} {{\n'
                f'    private readonly List<{type_name}> {field};\n'
                f'    public {unit}(List<{type_name}> {field}) {{ this.{field} = {field}; }}\n'
                f'    public override int {operation}(Ctx ctx) {{\n        {body_text}\n'
                f'        return {accumulator};\n    }}\n}}\n')
    if language == 'cpp':
        statements = [f'int {line};' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct};')
        else:
            inner = ' '.join(f'{line};' for line in body)
            statements.append(f'for (auto const& {element} : {loop}) {{ {inner} }}')
        body_text = '\n        '.join(statements)
        return (f'#include <vector>\n'
                f'class Ctx {{}};\n'
                f'class {type_name} {{ public: virtual int {operation}(Ctx& ctx) const {{ return 0; }} }};\n'
                f'class {unit} : public {type_name} {{\n'
                f'    std::vector<{type_name}*> {field};\n'
                f'public:\n'
                f'    explicit {unit}(std::vector<{type_name}*> c) : {field}(c) {{}}\n'
                f'    int {operation}(Ctx& ctx) const override {{\n        {body_text}\n'
                f'        return {accumulator};\n    }}\n}};\n')
    if language == 'go':
        statements = [f'{line.replace(" = ", " := ")}' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct}')
        else:
            inner = '\n        '.join(body)
            statements.append(f'for _, {element} := range {loop} {{\n        {inner}\n    }}')
        body_text = '\n    '.join(statements)
        return (f'package composite\n'
                f'type Ctx struct{{}}\n'
                f'type {type_name} interface{{ {operation}(ctx Ctx) int }}\n'
                f'type {unit} struct{{ {field} []{type_name} }}\n'
                f'func (s *{unit}) {operation}(ctx Ctx) int {{\n'
                f'    {body_text}\n    return {accumulator}\n}}\n')
    if language == 'rust':
        statements = [f'let mut {line};' for line in prelude]
        if loop is None:
            statements.append(f'{accumulator} += {direct};')
        else:
            inner = '\n            '.join(f'{line};' for line in body)
            statements.append(f'for {element} in {loop}.iter() {{\n            {inner}\n        }}')
        body_text = '\n        '.join(statements)
        return (f'struct Ctx;\n'
                f'trait {type_name} {{ fn {operation}(&self, ctx: &Ctx) -> i32; }}\n'
                f'struct {unit} {{ {field}: Vec<Box<dyn {type_name}>> }}\n'
                f'impl {type_name} for {unit} {{\n'
                f'    fn {operation}(&self, ctx: &Ctx) -> i32 {{\n        {body_text}\n'
                f'        {accumulator}\n    }}\n}}\n')
    raise AssertionError(language)


def callback_source(language, names=None):
    """The unimplemented callback form: ``reduce``/``sum`` instead of a loop."""
    n = names or DEFAULT_NAMES
    type_name, unit, field = n['type'], n['unit'], n['field']
    operation, accumulator, element = n['operation'], n['accumulator'], n['element']
    if language == 'python':
        return (f'class {type_name}:\n'
                f'    def {operation}(self, ctx):\n        return 0\n\n'
                f'class {unit}({type_name}):\n'
                f'    def __init__(self, {field}):\n        self.{field} = {field}\n\n'
                f'    def {operation}(self, ctx):\n'
                f'        return sum({element}.{operation}(ctx) for {element} in self.{field})\n')
    annotation = ': number' if language == 'typescript' else ''
    typed = ': Ctx' if language == 'typescript' else ''
    param_type = f': {type_name}[]' if language == 'typescript' else ''
    declared = f'  {field}: {type_name}[];\n' if language == 'typescript' else ''
    ctx_class = 'class Ctx {}\n' if language == 'typescript' else ''
    return (f'{ctx_class}'
            f'class {type_name} {{ {operation}(ctx{typed}){annotation} {{ return 0; }} }}\n'
            f'class {unit} extends {type_name} {{\n{declared}'
            f'  constructor({field}{param_type}) {{ super(); this.{field} = {field}; }}\n'
            f'  {operation}(ctx{typed}){annotation} {{\n'
            f'    return this.{field}.reduce(({accumulator}, {element}) => '
            f'{accumulator} + {element}.{operation}(ctx), 0);\n  }}\n}}\n')


def build(language, mode, names=None):
    text = callback_source(language, names) if mode == 'callback' else source(language, mode, names)
    graph = link_project([lower_source(text, language,
                                       f'composite.{EXTENSIONS[language]}')])
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
def test_aggregated_traversal_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    bindings = matches[0]['bindings']
    # The composite is the unit, and the roles name four different entities.
    assert '/CLASS:' in bindings['$unit']
    assert bindings['$operation'] != bindings['$child_call']
    assert bindings['$accumulator'] != bindings['$iterable']
    assert bindings['$element'] != bindings['$accumulator']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    assert detect(language, 'positive', names=RENAMED_NAMES)


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in BOUNDARY_MODES])
def test_a_reassigned_element_is_not_yet_rejected(language, mode):
    """Boundary: the element binding may be written again inside the loop.

    The update is not modelled as invalidating the iterated value, and the ``+=``
    that publishes the total marks the callable ``binding-writes/1`` unsupported,
    so no write count is available to require "the element was not re-assigned".
    """
    assert detect(language, mode)


@pytest.mark.parametrize('language', CALLBACK_LANGUAGES)
def test_the_callback_fold_shape_is_not_yet_detected(language):
    """Boundary: ``reduce``/``sum`` over the children is the unimplemented half.

    The IR emits no ``ITERATED_CALL`` for a callback, because the callback's
    element parameter is not linked to the collection it iterates.
    """
    assert not detect(language, 'callback')


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_aggregated_traversal(language):
    assert detect(language, 'positive', rule=ROOT)


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    query = row['query']
    assert query.startswith('language "kql/2";')
    for clause in ['iterate $iterable as $element',
                   'let $child_call = call $operation { receiver: $element;',
                   '$accumulator += $child_call as $write',
                   'return $accumulator;']:
        assert clause in query, clause


def test_rust_tail_expression_returns_the_declared_accumulator():
    """Rust's implicit return must not become the accumulator's declaring site.

    The block's tail expression is visited before the block's ``let`` statements
    (``block`` is pre-order), so a read arriving first used to register the slot
    at its own byte -- after the loop. A body walk anchors ``var $accumulator``
    on the declaration, which made rust need the loop before ``var`` while the
    other languages needed the reverse. The declared names are bound first.
    """
    text = source('rust', 'positive')
    name = DEFAULT_NAMES['accumulator']
    graph = build('rust', 'positive')
    declared_at = text.index(f'let mut {name}') + len('let mut ')
    storage = next(entity for entity in graph.entities.values()
                   if entity.kind == 'STORAGE' and entity.name == name)
    assert storage.attrs['start_byte'] == declared_at
    assert storage.attrs['declared'] is True
    method = next(entity for entity in graph.entities.values()
                  if entity.kind == 'CALLABLE' and entity.name == DEFAULT_NAMES['operation'])
    assert any(fact.relation == 'RETURNS_STORAGE' and fact.object == storage.id
               for fact in graph.facts), 'the method must return the declared slot'
