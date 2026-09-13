"""Iterator protocols are separate from bounded traversal correctness."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project


CURSORS = {
    'python': '''class Cursor:
 def __init__(self,values): self.values=values; self.index=0
 def __iter__(self): return self
 def __next__(self):
  if self.index >= len(self.values): raise StopIteration
  value=self.values[self.index]
  self.index=self.index+1
  return value
''',
    'java': '''class Cursor {
 int[] values; int index;
 Cursor(int[] values){this.values=values;this.index=0;}
 boolean hasNext(){return this.index<this.values.length;}
 int next(){
  if(!hasNext())throw new java.util.NoSuchElementException();
  int value=this.values[this.index];
  this.index=this.index+1;
  return value;
 }
}''',
    'typescript': '''class Cursor {
 values:number[]; index:number=0;
 constructor(values:number[]){this.values=values;}
 hasNext():boolean{return this.index<this.values.length;}
 next():number{
  if(!this.hasNext())throw new Error("exhausted");
  const value=this.values[this.index];
  this.index=this.index+1;
  return value;
 }
}''',
}


def instrument(text, language):
    if language == 'python':
        return text.replace('  self.index=self.index+1', '  metric=1+2\n  print(metric)\n  self.index=self.index+1')
    noise = 'int metric=1+2; System.out.println(metric);' if language == 'java' else 'const metric=1+2; console.log(metric);'
    return text.replace('this.index=this.index+1;', noise+' this.index=this.index+1;')


def detect(text, language):
    graph = link_project([lower_source(text, language, 'iterator.'+{'python':'py','java':'java','typescript':'ts','javascript':'js'}[language])])
    assert not graph.diagnostics, graph.diagnostics
    rules = builtin_rules()
    result = execute_rules(graph, [named_rule('iterator', rules)], registry=rules)
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', CURSORS)
@pytest.mark.parametrize('noise', [False,True])
def test_bounded_sequence_cursor_survives_work_between_read_and_advance(language, noise):
    assert detect(instrument(CURSORS[language], language) if noise else CURSORS[language], language)


@pytest.mark.parametrize('language', CURSORS)
def test_cursor_without_observable_advance_is_rejected(language):
    text = instrument(CURSORS[language], language).replace('  self.index=self.index+1\n', '').replace('this.index=this.index+1;', '')
    assert not detect(text, language)


@pytest.mark.parametrize('language', CURSORS)
@pytest.mark.parametrize('mutation', ['no-progress','unrelated-result'])
@pytest.mark.xfail(strict=True, reason='Finite-sequence refinement does not prove numeric progress or returned element provenance')
def test_requested_finite_sequence_contract_rejects_broken_traversal(language, mutation):
    text = instrument(CURSORS[language], language)
    if mutation == 'no-progress':
        text = text.replace('index+1', 'index+0')
    else:
        text = text.replace('return value', 'return 0')
    assert not detect(text, language)


GENERATORS = {
    'python': '''def entries(values):
 metric=1+2
 print(metric)
 yield from values
''',
    'javascript': '''function* entries(values){const metric=1+2;console.log(metric);yield* values;}''',
    'typescript': '''function* entries(values:Iterable<number>){const metric=1+2;console.log(metric);yield* values;}''',
}


@pytest.mark.parametrize('language', GENERATORS)
def test_delegation_shape_survives_independent_work(language):
    assert detect(GENERATORS[language], language)


@pytest.mark.parametrize('language', GENERATORS)
def test_returning_iterable_without_yield_is_not_generator_shape(language):
    text = GENERATORS[language].replace('yield from values', 'return values').replace('yield* values', 'return values')
    assert not detect(text, language)


ASYNC = {
    'python': '''async def entries(values):
 async for value in values:
  print(123)
  yield value
''',
    'javascript': '''async function* entries(values){for await(const value of values){console.log(123);yield value;}}''',
    'typescript': '''async function* entries(values:AsyncIterable<number>){for await(const value of values){console.log(123);yield value;}}''',
}


@pytest.mark.parametrize('language', ASYNC)
def test_async_generator_shape_is_not_a_proof_of_async_protocol_correctness(language):
    assert detect(ASYNC[language], language)


@pytest.mark.parametrize('language', GENERATORS)
def test_generator_name_and_logging_alone_do_not_imply_iterator(language):
    text = GENERATORS[language].replace(' yield from values\n', ' pass\n').replace('yield* values;', '')
    assert not detect(text, language)
