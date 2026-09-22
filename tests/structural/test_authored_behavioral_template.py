"""Authored Template Method: extension dispatch and actual step data dependence."""
from pathlib import Path
import tomllib
import pytest
from ken.kql2.catalog import compile_source
from ken.structural.frontend import lower_source
from ken.structural.query_view import query_graph
from ken.structural.semantic import link_project
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget

CATALOG=Path(__file__).parents[2]/'src/ken/structural/patterns/template-method.toml'
def query(identifier):
    data=tomllib.loads(CATALOG.read_text())
    return next(x['query'] for x in data['variants']+data['operations'] if x['id']==identifier)
def execute(source, language, identifier):
    index=query_graph(link_project([lower_source(source,language,'sample.'+language)]))
    result=Executor(index,{},QueryBudget()).execute(compile_source(query(identifier)))
    assert result['complete'],result
    return result

SOURCES={
 'python':'''class Base:
 def first(self,x): return x
 def second(self,x): return x
 def run(self,x,other:Base):
  prepared=self.first(x)
  print(123)
  return self.second(prepared)
class Derived(Base):
 def first(self,x): return x*2
''',
 'java':'''class Base { int first(int x){return x;} int second(int x){return x;}
 int run(int x,Base other){int prepared=this.first(x); log(); return this.second(prepared);} }
 class Derived extends Base { int first(int x){return x*2;} }''',
 'typescript':'''class Base { first(x:number){return x;} second(x:number){return x;}
 run(x:number,other:Base){const prepared=this.first(x); log(); return this.second(prepared);} }
 class Derived extends Base { first(x:number){return x*2;} }''',
}
@pytest.mark.parametrize('language',SOURCES)
@pytest.mark.parametrize('mutation',['positive','wrong_receiver','discarded_result','no_override'])
def test_dependent_steps_contract(language,mutation):
    source=SOURCES[language]
    if mutation=='wrong_receiver':source=source.replace('self.first(x)','other.first(x)').replace('this.first(x)','other.first(x)')
    if mutation=='discarded_result':source=source.replace('second(prepared)','second(0)')
    if mutation=='no_override':source=source[:source.index('class Derived')]
    result=execute(source,language,'dependent_steps')
    assert bool(result['matches']) is (mutation=='positive'),result

@pytest.mark.parametrize('language',SOURCES)
def test_virtual_hook_source_authoring(language):
    assert execute(SOURCES[language],language,'virtual-skeleton')['matches']

COMPOSED={
 'python': 'def algorithm(prepare,transform,finish):\n first=prepare()\n print(1)\n second=transform(first)\n finish(second)\n',
 'typescript': 'function algorithm(prepare:()=>number,transform:(x:number)=>number,finish:(x:number)=>void){let first=prepare();log();let second=transform(first);finish(second);}',
 'go': 'package p\nfunc algorithm(prepare func() int, transform func(int) int, finish func(int)){ first:=prepare(); println(1); second:=transform(first); finish(second) }',
}
@pytest.mark.parametrize('language',COMPOSED)
@pytest.mark.parametrize('mutation',['positive','wrong_first','wrong_second','overwrite'])
def test_composed_steps_conserve_results(language,mutation):
    source=COMPOSED[language]
    if mutation=='wrong_first':source=source.replace('transform(first)','transform(0)')
    if mutation=='wrong_second':source=source.replace('finish(second)','finish(0)')
    if mutation=='overwrite':
        source=source.replace('second=transform(first)','first=0\n second=transform(first)') if language=='python' else source.replace('second:=transform(first)','first=0;second:=transform(first)') if language=='go' else source.replace('let second=transform(first)','first=0;let second=transform(first)')
    result=execute(source,language,'composed-skeleton')
    assert bool(result['matches']) is (mutation=='positive'),result

@pytest.mark.parametrize('mutation',['positive','discarded','reordered'])
def test_interface_functional_composition_java(mutation):
 source='''interface Prepare { int apply(); }
 interface Transform { int apply(int x); }
 interface Finish { void apply(int x); }
 class Algorithm { void execute(Prepare prepare,Transform transform,Finish finish){
 int first=prepare.apply(); log(); int second=transform.apply(first); finish.apply(second);
 } }'''
 if mutation=='discarded':source=source.replace('transform.apply(first)','transform.apply(0)')
 if mutation=='reordered':source=source.replace('int first=prepare.apply(); log(); int second=transform.apply(first); finish.apply(second);','int first=0;int second=transform.apply(first); first=prepare.apply();finish.apply(second);')
 result=execute(source,'java','composed-skeleton')
 assert bool(result['matches']) is (mutation=='positive'),result


def test_trait_is_a_typedecl_and_uses_default_hook_on_its_receiver():
 source='''trait Algorithm {
 fn hook(&self, x:i32) -> i32;
 fn run(&self,x:i32)->i32 { self.hook(x) }
 }
 struct Concrete;
 impl Algorithm for Concrete { fn hook(&self,x:i32)->i32{x*2} }
 '''
 result=execute(source,'rust','trait-default')
 assert result['matches'],result
