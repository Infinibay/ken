"""Operators and ordered operand occurrences, independent of API or pattern names."""
import pytest
from ken.structural.frontend import lower_source


@pytest.mark.parametrize('language,source',[
 ('python','def f(a,b):\n x=a+b\n return a<=b\n'),
 ('javascript','function f(a,b){let x=a+b;return a<=b;}'),
 ('typescript','function f(a:number,b:number){let x=a+b;return a<=b;}'),
 ('java','class C{boolean f(int a,int b){int x=a+b;return a<=b;}}'),
 ('csharp','class C{bool F(int a,int b){int x=a+b;return a<=b;}}'),
 ('cpp','bool f(int a,int b){int x=a+b;return a<=b;}'),
 ('go','package p;func f(a,b int)bool{x:=a+b;_=x;return a<=b}'),
 ('rust','fn f(a:i32,b:i32)->bool{let x=a+b;return a<=b;}'),
])
def test_basic_operations_across_languages(language,source):
    g=lower_source(source,language,'sample')
    assert not g.diagnostics
    ops={o.id:o for o in g.operations}
    for token,kind in [('+','BINARY'),('<=','COMPARE')]:
        fact=next(f for f in g.facts if f.relation=='OPERATOR' and f.object==token)
        assert ops[fact.subject].kind==kind
        operands=[f for f in g.facts if f.relation=='OPERAND' and f.subject==fact.subject]
        assert len(operands)==2 and [f.attrs['position']for f in operands]==[0,1]
        assert all(f.object in ops for f in operands)


@pytest.mark.parametrize('token',['+','-','*','/','//','%','**','<','>','<=','>=','==','!=','&','|','^','<<','>>','and','or','in','is'])
def test_python_operator_spelling(token):
    g=lower_source(f'def f(a,b):\n return a {token} b\n','python','sample')
    assert not g.diagnostics
    assert any(f.relation=='OPERATOR' and f.object==token for f in g.facts)


def test_chained_comparisons_keep_three_operands_and_two_operators():
    g=lower_source('def f(a,b,c):\n return a < b <= c\n','python','sample')
    comparisons=[f for f in g.facts if f.relation=='OPERATOR']
    assert [(f.object,f.attrs['position'])for f in comparisons]==[('<',0),('<=',1)]
    operands=[f for f in g.facts if f.relation=='OPERAND' and f.subject==comparisons[0].subject]
    assert [f.attrs['position']for f in operands]==[0,1,2]


def test_short_circuit_is_not_eager_bitwise():
    g=lower_source('function f(a,b){return (a && b) | (a || b);}','javascript','sample')
    flags={f.object:f.attrs['short_circuit']for f in g.facts if f.relation=='OPERATOR'}
    assert flags=={'|':False,'&&':True,'||':True}
