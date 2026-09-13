"""KenQL return values use supported flow facts, independently of pattern names."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.kenql import query_graph
from ken.structural.model import IR
from ken.structural.rules import SavedRule, builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']
RETURNED = '''query returned {
 callable(name: clone) as $method;
 require $method RETURNS_VALUE $value [basis: flow];
 require $construction RESULT $value;
 require $construction ALLOCATES_TYPE $type;
 type_decl(name: Product) as $type;
 emit $construction;
}'''


def source(language, statements, builder=False):
    if language == 'python':
        product = 'class Product:\n def __init__(self,count): self.count=count\n'
        owner = 'class Builder:\n def configure(self,count): self.count=count\n' if builder else ''
        body = '\n'.join('  ' + s.replace('let ', '') for s in statements)
        return product + owner + ' def clone(self,flag):\n' + body + '\n'
    body = ';'.join(s.replace('self.', 'this.').replace('None', 'null')
                   .replace('Product(', 'new Product(') for s in statements) + ';'
    if language in {'javascript', 'typescript'}:
        product = 'class Product {count;constructor(count){this.count=count;}'
        owner = '}class Builder {count;configure(count){this.count=count;}' if builder else ''
        return product + owner + 'clone(flag){' + body + '}}'
    body = body.replace('let ', 'Product ')
    product = 'class Product {int count;Product(int count){this.count=count;}'
    owner = '}class Builder {int count;void configure(int count){this.count=count;}' if builder else ''
    return product + owner + 'Product clone(' + ('boolean' if language == 'java' else 'bool') + ' flag){' + body + '}}'


def run(language, statements, *, possible=False, builder=False):
    graph = link_project([lower_source(source(language, statements, builder), language, 'returned')])
    assert not graph.diagnostics
    registry = builtin_rules()
    pattern = 'builder#mutable-product' if builder else 'prototype#explicit-copy'
    result = execute_rules(graph, [SavedRule('returned', RETURNED), named_rule(pattern, registry)],
                           registry=registry, evidence_mode='possible' if possible else 'strict')
    assert result['complete']
    return graph, result


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('statements,expected', [
    (['return Product(self.count)'], True),
    (['let p=Product(self.count)', 'return p'], True),
    (['let p=Product(self.count)', 'let alias=p', 'return alias'], True),
    (['let p=Product(self.count)', 'let alias=p', 'p=None', 'return alias'], True),
    (['let p=Product(self.count)', 'let alias=p', 'alias=None', 'return p'], True),
    (['let p=Product(self.count)', 'p=None', 'return p'], False),
    (['let p=None', 'let alias=p', 'p=Product(self.count)', 'return alias'], False),
    (['return None', 'return Product(self.count)'], False),
    (['let p=None', 'return p', 'p=Product(self.count)'], False),
    (['let p=Product(self.count)', 'return p', 'p=None'], True),
])
@pytest.mark.parametrize('builder', [False, True])
def test_return_values_and_saved_patterns_share_current_origin(language, statements, expected, builder):
    _, result = run(language, statements, builder=builder)
    generic = [m for m in result['matches'] if m['id'] == 'returned']
    pattern = [m for m in result['matches'] if m['id'] != 'returned']
    assert bool(generic) is expected and bool(pattern) is expected


@pytest.mark.parametrize('language', LANGUAGES)
def test_branch_uncertainty_is_not_promoted_to_certain(language):
    branch = 'if flag:\n   p=None' if language == 'python' else 'if(flag){p=None;}'
    statements = ['let p=Product(self.count)', branch, 'return p']
    graph, strict = run(language, statements)
    _, possible = run(language, statements, possible=True)
    assert not strict['matches']
    assert len(possible['matches']) == 2
    view = query_graph(graph).ir
    edges = [f for f in view.facts if f.relation == 'RETURNS_VALUE' and f.attrs.get('basis') == 'flow']
    assert len(edges) == 2 and all(f.attrs['modality'] == 'may' for f in edges)


@pytest.mark.parametrize('language', LANGUAGES)
def test_same_operand_at_two_returns_preserves_occurrence_evidence(language):
    branch = 'if flag:\n   return p' if language == 'python' else 'if(flag){return p;}'
    graph, result = run(language, ['let p=Product(self.count)', branch, 'return p'])
    assert len(result['matches']) == 2  # One allocation and one pattern, with alternative proofs.
    edges = [f for f in query_graph(graph).ir.facts if f.relation == 'RETURNS_VALUE' and f.attrs.get('basis') == 'flow']
    assert len(edges) == 2
    assert len({f.attrs['return_operation'] for f in edges}) == 2
    assert len({f.object for f in edges}) == 1


def test_source_graph_unchanged_and_query_round_trip():
    graph, _ = run('python', ['let p=Product(self.count)', 'return p'])
    before = graph.to_dict()
    view = query_graph(graph).ir
    assert graph.to_dict() == before
    assert not any(f.relation == 'RETURNS_VALUE' for f in graph.facts)
    restored = IR.from_dict(view.to_dict())
    assert query_graph(restored).ir.to_dict() == view.to_dict()


def test_parameter_alias_normalizes_to_original_parameter_load():
    graph = link_project([lower_source('def f(value):\n alias=value\n return alias\n', 'python', 'parameter')])
    view = query_graph(graph).ir
    returned = next(f.object for f in view.facts if f.relation == 'RETURNS_VALUE')
    loaded = next(f.object for f in view.facts if f.relation == 'LOADED_FROM' and f.subject == returned)
    assert graph.entities[loaded].kind == 'PARAMETER' and graph.entities[loaded].name == 'value'


@pytest.mark.parametrize('body', [
    'while flag:\n   break\n  return Product(self.count)',
    'try:\n   return Product(self.count)\n  finally:\n   cleanup()',
    'yield 1\n  return Product(self.count)',
])
def test_unsupported_scopes_keep_syntax_projection_with_explicit_basis(body):
    graph, result = run('python', [body])
    assert not [m for m in result['matches'] if m['id'] == 'returned']
    assert [m for m in result['matches'] if m['id'] == 'prototype#explicit-copy']
    returned = [f for f in query_graph(graph).ir.facts if f.relation == 'RETURNS_VALUE']
    assert returned and all(f.attrs.get('basis') == 'syntax' for f in returned)
