"""Control joins kill replaced values and retain alternatives explicitly."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def graph(language, then, otherwise, prefix='x=Product()', tail='return x'):
    if language == 'python':
        code = 'class Product: pass\ndef f(flag):\n '+prefix+'\n if flag:\n  '+then+'\n'
        if otherwise is not None: code += ' else:\n  '+otherwise+'\n'
        code += ' '+tail+'\n'
    else:
        init = ('let ' if language in {'javascript','typescript'} else 'Product ')+prefix
        body=init+';if(flag){'+then+';}'+('else{'+otherwise+';}' if otherwise is not None else '')+tail+';'
        body=body.replace('None','null').replace('Product()','new Product()')
        code='class Product {} '+('function f(flag){'+body+'}' if language in {'javascript','typescript'} else 'class C { Product f(bool flag){'+body+'} }')
        if language=='java': code=code.replace('bool flag','boolean flag')
    g=link_project([lower_source(code,language,'sample')])
    assert not g.diagnostics
    assert any(f.relation=='RETURN_FLOW_STATUS' and f.object=='supported' for f in g.facts)
    return g


@pytest.mark.parametrize('language',['python','javascript','typescript','java','csharp'])
@pytest.mark.parametrize('then,otherwise,expected_origins',[
    ('x=None','x=None',1),
    ('x=None',None,2),
    ('x=Product()','x=None',2),
    ('return None','x=None',1),
])
def test_branch_origins(language,then,otherwise,expected_origins):
    g=graph(language,then,otherwise)
    origins=[f for f in g.facts if f.relation=='RETURN_ORIGIN']
    assert len({f.object for f in origins})==expected_origins
    if expected_origins==2:
        assert all(f.attrs['modality']=='may' for f in origins)
        assert all(f.attrs.get('modality')=='may' for f in g.facts if f.relation=='RETURNS_NEW')
    else:
        assert not any(f.relation=='RETURNS_NEW' for f in g.facts)


def test_python_multiple_elif_arms_all_replace_product():
    source='class Product: pass\ndef f(a,b,c):\n x=Product()\n if a:\n  x=None\n elif b:\n  x=None\n elif c:\n  x=None\n else:\n  x=None\n return x\n'
    g=link_project([lower_source(source,'python','sample')])
    assert not any(f.relation=='RETURNS_NEW' for f in g.facts)
    assert any(f.relation=='RETURN_ORIGIN' and f.object=='NULL' for f in g.facts)


def test_branch_return_does_not_join_terminated_environment():
    g=graph('python','return x','x=None')
    origins=[f for f in g.facts if f.relation=='RETURN_ORIGIN']
    assert len(origins)==2 and all(f.attrs['modality']=='must' for f in origins)


def test_unknown_binding_on_one_arm_is_not_silently_removed():
    code='class Product: pass\ndef f(flag):\n if flag:\n  x=Product()\n return x\n'
    g=link_project([lower_source(code,'python','sample')])
    assert not any(f.relation=='RETURN_ORIGIN' for f in g.facts)
    assert any(f.relation=='RETURN_FLOW_STATUS' and f.attrs.get('reason')=='unknown-binding' for f in g.facts)
