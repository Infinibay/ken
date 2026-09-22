"""Interpreter ``expression-sum``: a tagged expression evaluated with a context.

The variant is a published rule, so the tests go through the registry name
``interpreter#expression-sum`` rather than a private copy of the query.

The sources are the tagged sum of ``composite#algebraic-tree`` with an evaluation
**context** threaded through the recursive calls, which is the shape the ficha names
("enum/sum type de constantes y suma con evaluación recursiva de ambos operandos"):

```
if self.kind == Kind::Num { return self.value; }
self.left.evaluate(ctx) + self.right.evaluate(ctx)
```

Both recursive calls must carry an argument loaded from the **same** parameter, so the
query proves the context correlation the ficha asks for. It does **not** prove that the
two results are combined rather than discarded -- that needs value flow from both calls
into the return, which the IR does not have, and it is the same gap
``expression-objects`` already declares. The negatives cover the enumerable part:
a constant instead of the context, a single operand, a branch that does not test the
tag, and no dispatch at all.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.kenql import query_graph
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

from .test_composite_algebraic_tree import NAMES, RENAMED, source as tagged_source

RULE = 'interpreter#expression-sum'
ROOT = 'interpreter'
LANGUAGES = ['typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'typescript': 'ts', 'java': 'java', 'csharp': 'cs', 'cpp': 'cpp',
              'go': 'go', 'rust': 'rs'}
# Every negative is the algebraic-tree negative plus the context clauses, or a
# context-specific break. ``no-context-argument`` and ``mixed-context`` are the two
# ways the context correlation fails.
NEGATIVES = ['no-context-argument', 'one-operand', 'no-tag-field', 'no-branch']
CONTEXT = 'ctx'
TAGGED_MODE = {'positive': 'positive', 'no-context-argument': 'positive',
               'one-operand': 'one-operand',
               'no-tag-field': 'no-tag-field', 'no-branch': 'no-branch'}


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'expression-sum')


def _thread_context(language, text, n, argument='ctx'):
    """Add the context parameter and thread it through the recursive calls."""
    operation = n['operation']
    exported = operation[:1].upper() + operation[1:]
    if language == 'rust':
        text = f'struct Ctx {{ depth: i32 }}\n\n' + text
        text = text.replace(f'fn {operation}(&self) -> i32', f'fn {operation}(&self, ctx: &Ctx) -> i32')
        return text.replace(f'.{operation}()', f'.{operation}({argument})')
    if language == 'typescript':
        text = f'class Ctx {{ depth = 0; }}\n\n' + text
        text = text.replace(f'{operation}(): number', f'{operation}(ctx: Ctx): number')
        return text.replace(f'.{operation}()', f'.{operation}({argument})')
    if language == 'java':
        text = 'class Ctx {}\n\n' + text
        text = text.replace(f'int {operation}() {{', f'int {operation}(Ctx ctx) {{')
        return text.replace(f'.{operation}()', f'.{operation}({argument})')
    if language == 'csharp':
        text = 'class Ctx {}\n\n' + text
        text = text.replace(f'int {operation}() {{', f'int {operation}(Ctx ctx) {{')
        return text.replace(f'.{operation}()', f'.{operation}({argument})')
    if language == 'cpp':
        text = 'class Ctx {};\n\n' + text
        text = text.replace(f'int {operation}() {{', f'int {operation}(Ctx& ctx) {{')
        return text.replace(f'->{operation}()', f'->{operation}({argument})')
    if language == 'go':
        text = text.replace('package tree\n\n', 'package tree\n\ntype Ctx struct{ depth int }\n\n')
        text = text.replace(f'{exported}() int {{', f'{exported}(ctx Ctx) int {{')
        return text.replace(f'.{exported}()', f'.{exported}({argument})')
    raise AssertionError(language)


def source(language, mode, names=None):
    n = names or NAMES
    argument = '0' if mode == 'no-context-argument' else 'ctx'
    text = tagged_source(language, TAGGED_MODE[mode], n)
    return _thread_context(language, text, n, argument)


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'expression.{EXTENSIONS[language]}')])
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
def test_tagged_expression_with_context_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    assert {m['bindings']['$unit'] for m in matches} == {
        f'expression.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}
    bindings = matches[0]['bindings']
    for role in ('$operation', '$first', '$second', '$branch', '$tested', '$context'):
        assert role in bindings, (language, role)
    assert bindings['$context'] not in {bindings['$first'], bindings['$second']}


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'positive', names=RENAMED)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'expression.{EXTENSIONS[language]}::module/CLASS:{RENAMED["unit"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_expression_sum(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'expression.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    # The legacy vocabulary named `TRUTH_TEST`, `TYPE`, `ARGUMENT` and `LOADED_FROM`;
    # the KQL 2 rewrite states the same four claims with a branch test on the tag
    # field, a self-typed operand field, the context argument both calls load and
    # the sibling-operand clause that ties the two evaluations to one statement.
    for spelling in ['if ($tested == _)', 'type: nominal($unit)',
                     'argument $context at 0', 'call alongside']:
        assert spelling in row['query'], spelling


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_context_argument_is_what_admits_the_evaluation(language):
    """The context half: both recursive calls must carry an argument loaded from the
    same parameter, and a constant instead stops the match."""
    view = query_graph(build(language, 'positive')).ir
    names = {key: entity.name for key, entity in view.entities.items()}
    loaded = {names.get(f.object, f.object) for f in view.facts if f.relation == 'LOADED_FROM'}
    assert CONTEXT in loaded, (language, loaded)
    assert not detect(language, 'no-context-argument')
