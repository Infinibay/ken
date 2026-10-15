from collections import defaultdict
from ken.parsers.python import parse_python_file
from ken.retrieval.description import describe_owner
from ken.retrieval.passages import extract_passages


def descriptions():
    source = b'''def outer(value):
    """Return the existing value with its context."""
    def child():
        return "private-child-body"
    return value
'''
    groups = defaultdict(list)
    for p in extract_passages(source, parse_python_file(source, 'toy.py'), path='toy.py', language='python'):
        groups[p.entity.qualname].append(p)
    return {name:describe_owner(ps) for name,ps in groups.items()}


def test_contract_has_own_documentation_and_signature_without_implementation():
    from context_views import owner_views
    d=descriptions()['outer'];views=owner_views(d)
    assert 'Return the existing value' in views['contract']
    assert 'outer' in views['contract'] and 'value' in views['contract']
    assert 'return value' not in views['contract']
    assert 'private-child-body' not in views['contract']


def test_implementation_uses_actual_owned_code_without_documentation_or_nested_body():
    from context_views import owner_views
    views=owner_views(descriptions()['outer'])
    assert 'return value' in views['implementation']
    assert 'Return the existing value' not in views['implementation']
    assert 'private-child-body' not in views['implementation']


def test_documentation_free_implementation_is_identical_to_existing_full_projection():
    from context_views import owner_views
    d=descriptions()['outer.child']
    assert not d.fields['documentation']
    expected='\n'.join([d.entity.path,d.fields['identity'],d.fields['signature'],'Documentation: ','Source:',d.fields['implementation']])
    assert owner_views(d)['implementation']==expected
