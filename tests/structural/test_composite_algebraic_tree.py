"""Composite ``algebraic-tree``: a tagged node with recursive operands.

The variant is a published rule, so the tests go through the registry name
``composite#algebraic-tree`` rather than a private copy of the query.

The shape is the tagged sum that every one of the six languages can spell without an
interface or a base class: an enum tag, a type holding the tag and the operands, and a
method that dispatches on the tag and recurses through **both** operands:

```
struct Expr { kind: Kind, value: i32, left: Box<Expr>, right: Box<Expr> }
if self.kind == Kind::Num { return self.value; }
self.left.evaluate() + self.right.evaluate()
```

The evidence is threefold, and the third is what separates this variant from
``recursive-nominal`` (which proves a uniform recursive call but not a dispatch):

* two fields of the type are typed by the type itself (``TYPE`` on a slot);
* the operation calls **its own name** on both of them;
* a branch of the operation discriminates a **field of the same type** -- published by
  ``TRUTH_TEST`` on the comparison (IR 1.71). Without it the query would only prove "a
  type with two recursive fields", which is weaker than the variant.

Not proven, and stated in ``query_claim``: that the tag values are distinct, that the
arms are exhaustive, that the leaf arm does not recurse, or that the operands are not
re-assigned. A real per-case sum encoding (Rust ``enum`` variants, TypeScript
discriminated unions, records) is **not** what this query accepts, and is not modelled
by the IR.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'composite#algebraic-tree'
ROOT = 'composite'
LANGUAGES = ['typescript', 'java', 'csharp', 'cpp', 'go', 'rust']
EXTENSIONS = {'typescript': 'ts', 'java': 'java', 'csharp': 'cs', 'cpp': 'cpp',
              'go': 'go', 'rust': 'rs'}
NAMES = {'unit': 'Expr', 'kind': 'Kind', 'tag': 'kind', 'value': 'value',
         'first': 'left', 'second': 'right', 'operation': 'evaluate',
         'case': 'Num'}
RENAMED = {'unit': 'Node', 'kind': 'Tag', 'tag': 'tag', 'value': 'payload',
           'first': 'lhs', 'second': 'rhs', 'operation': 'size', 'case': 'Leaf'}
# Each negative breaks one link: the branch does not discriminate a field of the type,
# only one operand is recursed on, the recursive call is a different operation, or
# there is no dispatch at all.
NEGATIVES = ['no-tag-field', 'one-operand', 'foreign-operation', 'no-branch']


def variant():
    rule = next(r for r in _load_catalog() if r.id == ROOT)
    return next(v for v in rule.variants if v['id'] == 'algebraic-tree')


def _pieces(language, mode, n):
    """The tag test, the recursive expression, and the probe the negatives insert."""
    tag = f'self.{n["tag"]}' if language == 'rust' else (
        f'this.{n["tag"]}' if language == 'typescript' else (
            f'e.{n["tag"]}' if language == 'go' else n['tag']))
    first, second = n['first'], n['second']
    call = {'cpp': '{e}->{op}()'}.get(language, '{e}.{op}()')
    if language == 'go':
        call = '{e}.{Op}()'
    operation = n['operation']
    exported = operation[:1].upper() + operation[1:] if language == 'go' else operation
    recursive = (call.format(e=first, op=exported, Op=exported)
                 + ' + ' + call.format(e=second, op=exported, Op=exported))
    foreign = (call.format(e=first, op='other', Op='Other')
               + ' + ' + call.format(e=second, op='other', Op='Other'))
    tested = tag if mode != 'no-tag-field' else 'probe'
    if mode == 'foreign-operation':
        expression = foreign
    elif mode == 'one-operand':
        expression = call.format(e=first, op=exported, Op=exported)
    else:
        expression = recursive
    return tested, expression, mode == 'no-branch'


def _body(language, mode, n):
    """The operation body, as a list of statements."""
    tested, expression, unconditional = _pieces(language, mode, n)
    value = n['value']
    case = n['case']
    if language == 'rust':
        returned = f'self.{value}' if mode != 'no-tag-field' else 'self.value'
        probe = ['let probe = self.kind;'] if mode == 'no-tag-field' else []
        test = f'if {tested} == {n["kind"]}::{case} {{'
        return probe + ([test, f'    return {returned};', '}'] if not unconditional else []) + [expression]
    if language == 'typescript':
        probe = ['const probe = this.kind;'] if mode == 'no-tag-field' else []
        test = f'if ({tested} === {n["kind"]}.{case}) {{'
        return probe + ([test, f'  return this.{value};', '}'] if not unconditional else []) + [f'return {expression};']
    if language == 'java':
        probe = [f'{n["kind"]} probe = {n["tag"]};'] if mode == 'no-tag-field' else []
        test = f'if ({tested} == {n["kind"]}.{case.upper()}) {{'
        return probe + ([test, f'    return {value};', '}'] if not unconditional else []) + [f'return {expression};']
    if language == 'csharp':
        probe = [f'{n["kind"]} probe = {n["tag"]};'] if mode == 'no-tag-field' else []
        test = f'if ({tested} == {n["kind"]}.{case}) {{'
        return probe + ([test, f'    return {value};', '}'] if not unconditional else []) + [f'return {expression};']
    if language == 'cpp':
        probe = [f'{n["kind"]} probe = {n["tag"]};'] if mode == 'no-tag-field' else []
        test = f'if ({tested} == {case}) {{'
        return probe + ([test, f'    return {value};', '}'] if not unconditional else []) + [f'return {expression};']
    if language == 'go':
        probe = [f'probe := e.{n["tag"]}'] if mode == 'no-tag-field' else []
        test = f'if {tested} == {case}Kind {{'
        return probe + ([test, f'    return e.{value}', '}'] if not unconditional else []) + [f'return {expression}']
    raise AssertionError(language)


def source(language, mode, names=None):
    n = names or NAMES
    body = _body(language, mode, n)
    if language == 'rust':
        statements = '\n        '.join(body)
        return (f'enum {n["kind"]} {{ {n["case"]}, Other }}\n\n'
                f'struct {n["unit"]} {{\n'
                f'    {n["tag"]}: {n["kind"]},\n'
                f'    {n["value"]}: i32,\n'
                f'    {n["first"]}: Box<{n["unit"]}>,\n'
                f'    {n["second"]}: Box<{n["unit"]}>,\n'
                f'}}\n\n'
                f'impl {n["unit"]} {{\n'
                f'    fn {n["operation"]}(&self) -> i32 {{\n        {statements}\n    }}\n}}\n')
    if language == 'typescript':
        statements = '\n    '.join(body)
        return (f'enum {n["kind"]} {{ {n["case"]}, Other }}\n\n'
                f'class {n["unit"]} {{\n'
                f'  {n["tag"]}: {n["kind"]};\n'
                f'  {n["value"]}: number;\n'
                f'  {n["first"]}: {n["unit"]};\n'
                f'  {n["second"]}: {n["unit"]};\n\n'
                f'  {n["operation"]}(): number {{\n    {statements}\n  }}\n}}\n')
    if language == 'java':
        statements = '\n        '.join(body)
        return (f'enum {n["kind"]} {{ {n["case"].upper()}, OTHER }}\n\n'
                f'class {n["unit"]} {{\n'
                f'    {n["kind"]} {n["tag"]};\n'
                f'    int {n["value"]};\n'
                f'    {n["unit"]} {n["first"]};\n'
                f'    {n["unit"]} {n["second"]};\n\n'
                f'    int {n["operation"]}() {{\n        {statements}\n    }}\n}}\n')
    if language == 'csharp':
        statements = '\n        '.join(body)
        return (f'enum {n["kind"]} {{ {n["case"]}, Other }}\n\n'
                f'class {n["unit"]} {{\n'
                f'    {n["kind"]} {n["tag"]};\n'
                f'    int {n["value"]};\n'
                f'    {n["unit"]} {n["first"]};\n'
                f'    {n["unit"]} {n["second"]};\n\n'
                f'    int {n["operation"]}() {{\n        {statements}\n    }}\n}}\n')
    if language == 'cpp':
        statements = '\n        '.join(body)
        return (f'enum {n["kind"]} {{ {n["case"]}, Other }};\n\n'
                f'class {n["unit"]} {{\npublic:\n'
                f'    {n["kind"]} {n["tag"]};\n'
                f'    int {n["value"]};\n'
                f'    {n["unit"]}* {n["first"]};\n'
                f'    {n["unit"]}* {n["second"]};\n\n'
                f'    int {n["operation"]}() {{\n        {statements}\n    }}\n}};\n')
    if language == 'go':
        statements = '\n    '.join(body)
        exported = n['operation'][:1].upper() + n['operation'][1:]
        return (f'package tree\n\n'
                f'type {n["kind"]} int\n\n'
                f'const (\n\t{n["case"]}Kind {n["kind"]} = iota\n\tOtherKind\n)\n\n'
                f'type {n["unit"]} struct {{\n'
                f'\t{n["tag"]}  {n["kind"]}\n'
                f'\t{n["value"]} int\n'
                f'\t{n["first"]}  *{n["unit"]}\n'
                f'\t{n["second"]} *{n["unit"]}\n'
                f'}}\n\n'
                f'func (e *{n["unit"]}) {exported}() int {{\n    {statements}\n}}\n')
    raise AssertionError(language)


def build(language, mode, names=None):
    graph = link_project([lower_source(source(language, mode, names), language,
                                       f'tree.{EXTENSIONS[language]}')])
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
def test_tagged_node_with_recursive_operands_is_detected(language):
    matches = detect(language, 'positive')
    assert matches, language
    assert {m['bindings']['$unit'] for m in matches} == {
        f'tree.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}
    bindings = matches[0]['bindings']
    for role in ('$operation', '$first', '$second', '$branch', '$tested'):
        assert role in bindings, (language, role)
    assert bindings['$first'] != bindings['$second']


@pytest.mark.parametrize('language', LANGUAGES)
def test_renamed_identifiers_preserve_detection(language):
    matches = detect(language, 'positive', names=RENAMED)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'tree.{EXTENSIONS[language]}::module/CLASS:{RENAMED["unit"]}'}


@pytest.mark.parametrize('language,mode', [(language, mode) for language in LANGUAGES
                                           for mode in NEGATIVES])
def test_negative_shapes_are_rejected(language, mode):
    assert not detect(language, mode)


@pytest.mark.parametrize('language', LANGUAGES)
def test_root_rule_reports_the_tagged_tree(language):
    matches = detect(language, 'positive', rule=ROOT)
    assert {m['bindings']['$unit'] for m in matches} == {
        f'tree.{EXTENSIONS[language]}::module/CLASS:{NAMES["unit"]}'}


def test_variant_declares_every_target_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    for relation in ['TRUTH_TEST', 'TYPE', 'HAS_FIELD', 'RECEIVER']:
        assert relation in row['query'], relation


@pytest.mark.parametrize('language', LANGUAGES)
def test_the_branch_test_is_what_admits_the_dispatch(language):
    """``TRUTH_TEST`` on the comparison is the dispatch half: without the tag test the
    node is only "two recursive fields", and the query stops matching."""
    tagged = build(language, 'positive')
    tested = [(f.subject, f.object) for f in tagged.facts if f.relation == 'TRUTH_TEST']
    assert len(tested) == 2, (language, tested)
    assert not detect(language, 'no-branch')
