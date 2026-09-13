"""Structured statement control preserves branches and loop exits."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project


def build(source, language):
    g=link_project([lower_source(source,language,'sample')])
    assert not g.diagnostics
    ops={o.id:o for o in g.operations}
    edges=[f for f in g.facts if f.relation=='CFG_NEXT']
    return g,ops,edges


@pytest.mark.parametrize('language,source',[
 ('python','def f(a):\n while a:\n  if a:\n   continue\n  break\n return a\n'),
 ('javascript','function f(a){while(a){if(a){continue;}break;}return a;}'),
 ('typescript','function f(a:boolean){while(a){if(a){continue;}break;}return a;}'),
 ('java','class C{boolean f(boolean a){while(a){if(a){continue;}break;}return a;}}'),
 ('csharp','class C{bool F(bool a){while(a){if(a){continue;}break;}return a;}}'),
 ('cpp','bool f(bool a){while(a){if(a){continue;}break;}return a;}'),
 ('rust','fn f(a:bool)->bool{while a{if a{continue;}break;}return a;}'),
])
def test_while_continue_and_break(language,source):
    g,ops,edges=build(source,language)
    loop=next(o.id for o in ops.values()if o.native_kind in {'while_statement','while_expression'})
    ret=next(o.id for o in ops.values()if o.native_kind in {'return_statement','return_expression'})
    assert any(f.object==loop and f.attrs['kind']=='continue' for f in edges)
    assert any(f.object==ret and f.attrs['kind']=='break' for f in edges)
    assert {f.attrs['kind']for f in edges if f.subject==loop}=={'true','false'}


@pytest.mark.parametrize('language,source',[
 ('javascript','function f(){for(let i=0;i<3;i++){continue;}return 1;}'),
 ('java','class C{int f(){for(int i=0;i<3;i++){continue;}return 1;}}'),
 ('csharp','class C{int F(){for(int i=0;i<3;i++){continue;}return 1;}}'),
 ('cpp','int f(){for(int i=0;i<3;i++){continue;}return 1;}'),
 ('go','package p;func f()int{for i:=0;i<3;i++{continue};return 1}'),
])
def test_for_continue_goes_through_update(language,source):
    g,ops,edges=build(source,language)
    continuation=next(f for f in edges if f.attrs['kind']=='continue')
    target=ops[continuation.object]
    assert target.role in {'increment','update'}
    assert any(f.subject==target.id and ops[f.object].native_kind=='for_statement' for f in edges if f.object in ops)


def test_python_loop_break_skips_else():
    g,ops,edges=build('def f(xs):\n for x in xs:\n  break\n else:\n  normal()\n after()\n','python')
    loop=next(o.id for o in ops.values()if o.native_kind=='for_statement')
    broken=next(f.object for f in edges if f.attrs['kind']=='break')
    exhausted=next(f.object for f in edges if f.subject==loop and f.attrs['kind']=='exhausted')
    assert broken!=exhausted
    assert ops[broken].line==6 and ops[exhausted].line==5


def test_elif_true_branch_joins_after_entire_chain():
    g,ops,edges=build('def f(a,b):\n if a:\n  first()\n elif b:\n  second()\n else:\n  third()\n after()\n','python')
    second=next(o.id for o in ops.values()if o.native_kind=='expression_statement' and o.line==5)
    follow=next(o.id for o in ops.values()if o.native_kind=='expression_statement' and o.line==8)
    assert any(f.subject==second and f.object==follow for f in edges)


def test_for_without_condition_has_no_false_exit():
    g,ops,edges=build('function f(){for(;;){work();}}','javascript')
    loop=next(o.id for o in ops.values()if o.native_kind=='for_statement')
    assert {f.attrs['kind']for f in edges if f.subject==loop}=={'true'}


def test_exception_scope_reports_partial_cfg():
    g,ops,edges=build('def f():\n try:\n  work()\n finally:\n  cleanup()\n','python')
    assert any(f.relation=='CFG_STATUS' and f.object=='partial' for f in g.facts)
