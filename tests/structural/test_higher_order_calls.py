"""Calling a produced callable differs from merely passing a call as argument."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import SavedRule, execute_rules

SOURCES = {
 'python': 'def run(adapt, x): return adapt(x)(x)',
 'javascript': 'function run(adapt, x) { return adapt(x)(x); }',
 'typescript': 'function run(adapt: (x:number)=>(y:number)=>number, x:number) { return adapt(x)(x); }',
 'go': 'package p; func run(adapt func(int)func(int)int, x int) int { return adapt(x)(x) }',
 'rust': 'fn run(adapt: fn(i32)->fn(i32)->i32, x:i32)->i32 { adapt(x)(x) }',
 'cpp': 'auto run(auto adapt, int x) { return adapt(x)(x); }',
 'csharp': 'class C { int Run(System.Func<int,System.Func<int,int>> adapt,int x) { return adapt(x)(x); } }',
}


def search(source, language):
    unit = lower_source(source, language, 'example')
    assert not unit.diagnostics
    g = link_project([unit])
    r = execute_rules(g, [SavedRule('higher-order', '''query higher_order {
        call() as $invoke;
        require $invoke INVOKES_RESULT_OF $producer;
        call() as $producer;
        different $invoke $producer;
        emit $invoke, $producer;
    }''')])
    assert r['complete']
    return r['matches']


@pytest.mark.parametrize('language', SOURCES)
@pytest.mark.parametrize('parentheses', [False, True])
def test_call_produced_callable(language, parentheses):
    source = SOURCES[language]
    if parentheses:
        source = source.replace('adapt(x)(x)', '(adapt(x))(x)')
    assert len(search(source, language)) == 1


@pytest.mark.parametrize('language', SOURCES)
def test_nested_argument_is_not_calling_produced_callable(language):
    assert not search(SOURCES[language].replace('adapt(x)(x)', 'adapt(adapt(x))'), language)
