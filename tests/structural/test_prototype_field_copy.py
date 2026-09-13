"""Returned allocations and last field writes stay correlated across aliases/branches.

Sources are parsed, lowered and queried; target programs are never executed.
"""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']


def source(language, statements):
    def render(items, depth):
        text = ''
        for item in items:
            if isinstance(item, tuple):
                _, yes, no = item
                if language == 'python':
                    text += ' ' * depth + 'if flag:\n' + render(yes, depth + 1)
                    if no is not None:
                        text += ' ' * depth + 'else:\n' + render(no, depth + 1)
                else:
                    text += 'if(flag){' + render(yes, depth) + '}'
                    if no is not None:
                        text += 'else{' + render(no, depth) + '}'
            elif language == 'python':
                text += ' ' * depth + item.replace('let ', '') + '\n'
            else:
                item = item.replace('self', 'this').replace('None', 'null')
                item = item.replace('Product()', 'new Product()')
                if language in {'java', 'csharp'}:
                    item = item.replace('let ', 'Product ')
                text += item + ';'
        return text

    body = render(statements, 2)
    if language == 'python':
        return 'class Product:\n def __init__(self): self.count=0\n def copy(self, flag):\n' + body
    if language in {'javascript', 'typescript'}:
        return 'class Product {count=0; copy(flag){' + body + '}}'
    boolean = 'boolean' if language == 'java' else 'bool'
    return 'class Product {int count; Product copy(' + boolean + ' flag){' + body + '}}'


def analyze(language, statements, *, possible=False):
    graph = link_project([lower_source(source(language, statements), language, 'copy')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('prototype#field-copy', registry)], registry=registry,
                           evidence_mode='possible' if possible else 'strict')
    assert result['complete']
    return graph, result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('statements,expected', [
    (['let p=Product()', 'p.count=self.count', 'return p'], True),
    (['let p=Product()', 'p.count=1', 'return p'], False),
    (['let p=Product()', 'p.count=self.count', 'p.count=1', 'return p'], False),
    (['let p=Product()', 'p.count=1', 'p.count=self.count', 'return p'], True),
    (['let p=Product()', 'p.other=self.count', 'return p'], False),
    (['let p=Product()', 'p.count=self.other', 'return p'], False),
    (['let p=Product()', 'let q=Product()', 'p.count=q.count', 'return p'], False),
    (['let p=Product()', 'p.count=self.count', 'return self'], False),
    (['let p=Product()', 'p.count=self.count', 'p=None', 'return p'], False),
    (['let p=Product()', 'p.count=self.count', 'p=Product()', 'return p'], False),
    (['let p=Product()', 'let q=Product()', 'q.count=self.count', 'return p'], False),
    (['let p=Product()', 'let q=p', 'q.count=self.count', 'return p'], True),
    (['let p=Product()', 'let q=p', 'p=None', 'q.count=self.count', 'return q'], True),
    (['let p=Product()', 'let q=p', 'p=Product()', 'q.count=self.count', 'return q'], True),
    (['let p=Product()', 'let q=p', 'p=Product()', 'q.count=self.count', 'return p'], False),
    (['let p=Product()', 'let q=p', 'q.count=self.count', 'p.count=1', 'return q'], False),
    (['let p=Product()', 'p.count=self.count', 'return p', 'p.count=1'], True),
    (['let p=Product()', 'p.count=1', 'return p', 'p.count=self.count'], False),
    (['let p=Product()', 'p.count=self.count', 'helper(p)', 'return p'], False),
    (['let p=Product()', 'p.count=self.count', 'p.reset()', 'return p'], False),
    (['let p=Product()', 'let q=p', 'p.count=self.count', 'helper(q)', 'return p'], False),
    (['let p=Product()', 'p.count=self.count', 'let q=Product()', 'helper(q)', 'return p'], True),
])
def test_field_copy_and_contrasting_uses(language, statements, expected):
    _, matches = analyze(language, statements)
    assert bool(matches) is expected


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('body,expected', [
    ([('if', ['p.count=self.count', 'return None'], None), 'return p'], False),
    ([('if', ['p.count=self.count', 'p=q'], ['q.count=self.count']), 'return p'], False),
    ([('if', ['p.count=self.count', 'p=q'], ['q.count=self.count', 'q=p']), 'return p'], False),
    (['p.count=self.count', ('if', ['p.count=1'], ['p.count=2']), 'return p'], False),
    ([('if', ['p.count=self.count'], ['p.count=self.count']), 'return p'], True),
    ([('if', ['p.count=self.count'], None), 'return p'], True),
    ([('if', ['p.count=self.count', 'return p'], ['q.count=self.count', 'return q'])], True),
])
def test_branch_return_object_and_field_write_are_correlated(language, body, expected):
    _, matches = analyze(language, ['let p=Product()', 'let q=Product()', *body], possible=True)
    assert bool(matches) is expected


@pytest.mark.parametrize('language', LANGUAGES)
def test_one_branch_copy_is_possible_evidence(language):
    statements = ['let p=Product()', ('if', ['p.count=self.count'], None), 'return p']
    graph, matches = analyze(language, statements)
    assert not matches
    evidence = [f for f in graph.facts if f.relation == 'RETURN_FIELD_STATE']
    assert evidence and all(f.attrs['modality'] == 'may' for f in evidence)
    assert analyze(language, statements, possible=True)[1]


@pytest.mark.parametrize('language', LANGUAGES)
def test_renaming_does_not_select_prototype(language):
    text = source(language, ['let p=Product()', 'p.count=self.count', 'return p'])
    text = text.replace('Product', 'Envelope').replace('copy', 'materialize').replace('count', 'payload')
    graph = link_project([lower_source(text, language, 'renamed')])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('prototype', registry)], registry=registry)
    assert result['complete'] and result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_ternary_field_rhs_is_opaque_without_blocking_other_copies(language):
    rhs = 'self.count if flag else 0' if language == 'python' else 'flag ? self.count : 0'
    assert analyze(language, ['let p=Product()', 'p.other=' + rhs, 'p.count=self.count', 'return p'])[1]
    assert not analyze(language, ['let p=Product()', 'p.count=' + rhs, 'return p'], possible=True)[1]


@pytest.mark.parametrize('use', ['helper([p])', 'helper({"value": p})', 'box=[p]', 'self.saved=p',
                                  'let q=p\n  helper([q])'])
def test_opaque_publication_does_not_certify_field_state(use):
    _, matches = analyze('python', ['let p=Product()', 'p.count=self.count', use, 'return p'], possible=True)
    assert not matches


def test_state_budget_does_not_publish_partial_field_evidence():
    body = ['let p=Product()', 'p.count=self.count']
    body += [('if', ['let q=Product()'], None)] * 9
    graph, matches = analyze('python', [*body, 'return p'], possible=True)
    assert not matches
    assert not any(f.relation == 'RETURN_FIELD_STATE' for f in graph.facts)
    assert any(f.relation == 'RETURN_FLOW_STATUS' and f.attrs.get('reason') == 'flow-states'
               for f in graph.facts)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('local', ['count', 'copy'])
def test_member_spelling_does_not_escape_same_named_local(language, local):
    assert analyze(language, [f'let {local}=Product()', f'{local}.count=self.count', f'return {local}'])[1]


@pytest.mark.parametrize('annotation,expected', [
    ('count: int', True), ('count: int | None', True),
    ('count: int = 0', False), ('count = 0', False),
    ('count=0\n count: int', False), ('count: int\n count=0', False),
    ('count: ClassVar[int]', False), ('count: typing.ClassVar[int]', False),
])
def test_python_annotation_does_not_initialize_class_storage(annotation, expected):
    text = 'class Product:\n ' + annotation + '\n def copy(self):\n  p=Product()\n  p.count=self.count\n  return p\n'
    graph = link_project([lower_source(text, 'python', 'annotated')])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('prototype#field-copy', registry)], registry=registry)
    assert result['complete'] and bool(result['matches']) is expected


def test_requests_shaped_copy_with_annotations_and_opaque_field_helpers():
    text = '''class PreparedRequest:
 method: str | None
 headers: dict[str, str]
 cookies: object
 def copy(self):
  p=PreparedRequest()
  p.method=self.method
  p.headers=self.headers.copy() if self.headers is not None else None
  p.cookies=copy_cookie_jar(self.cookies)
  return p
'''
    graph = link_project([lower_source(text, 'python', 'requests-shaped')])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('prototype', registry)], registry=registry)
    assert result['complete'] and len(result['matches']) == 1


@pytest.mark.parametrize('language', LANGUAGES)
def test_copy_into_different_nominal_type_is_not_this_variant(language):
    text = source(language, ['let p=Product()', 'p.count=self.count', 'return p'])
    text = text.replace('p=Product()', 'p=Other()').replace('p=new Product()', 'p=new Other()')
    text = ('class Other: pass\n' if language == 'python' else 'class Other {}\n') + text
    graph = link_project([lower_source(text, language, 'other')])
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('prototype#field-copy', registry)], registry=registry)
    assert result['complete'] and not result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_compound_field_update_does_not_reuse_earlier_copy(language):
    graph, matches = analyze(language, ['let p=Product()', 'p.count=self.count', 'p.count+=1', 'return p'], possible=True)
    assert not matches and not any(f.relation == 'RETURN_FIELD_STATE' for f in graph.facts)
