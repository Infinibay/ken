"""Retry must correlate the successful attempt, handler and target loop."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


SOURCES = {
    'python': 'def f():\n while True:\n  try:\n   return work()\n  except Error:\n   continue\n',
    'javascript': 'function f(){for(;;){try{return work();}catch(e){continue;}}}',
    'typescript': 'function f(){for(;;){try{return work();}catch(e){continue;}}}',
    'java': 'class A { Object f(){while(true){try{return work();}catch(Exception e){continue;}}}}',
    'csharp': 'class A { object F(){while(true){try{return work();}catch(Exception){continue;}}}}',
    'cpp': 'int f(){while(true){try{return work();}catch(...){continue;}}}',
}


def scan(source, language):
    graph = link_project([lower_source(source, language, 'sample')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('resilience.exception-retry', registry)], registry=registry)
    assert result['complete']
    return result['matches']


@pytest.mark.parametrize('language', SOURCES)
def test_retry_and_renaming(language):
    assert scan(SOURCES[language], language)
    assert scan(SOURCES[language].replace('work', 'fetch'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_break_on_failure_is_not_retry(language):
    assert not scan(SOURCES[language].replace('continue', 'break'), language)


@pytest.mark.parametrize('language', SOURCES)
def test_constant_return_is_not_attempt(language):
    assert not scan(SOURCES[language].replace('work()', '1'), language)


@pytest.mark.parametrize('language', ['javascript', 'typescript', 'java', 'csharp', 'cpp'])
def test_continue_of_nested_loop_is_not_retry_of_outer_attempt(language):
    assert not scan(SOURCES[language].replace('continue;', 'while(true){continue;}'), language)


@pytest.mark.parametrize('language', ['javascript', 'typescript', 'java'])
def test_labelled_continue_not_guessed(language):
    source = SOURCES[language].replace('continue;', 'continue outer;')
    assert not scan(source, language)


def test_python_inner_function_return_not_outer_success():
    source = 'def f():\n while True:\n  try:\n   def g():\n    return work()\n  except Error:\n   continue\n'
    assert not scan(source, 'python')


def test_success_from_other_try_is_not_correlated():
    source = 'function f(){for(;;){try{return work();}catch(e){break;} try{other();}catch(e){continue;}}}'
    assert not scan(source, 'javascript')


@pytest.mark.parametrize('language', ['javascript', 'typescript'])
def test_async_returned_attempt(language):
    source = SOURCES[language].replace('function f', 'async function f').replace('return work()', 'return await work()')
    assert scan(source, language)


def test_context_projection_does_not_depend_on_operation_order():
    unit = lower_source(SOURCES['python'], 'python', 'sample')
    normal = link_project([unit])
    unit.operations.reverse()
    reversed_graph = link_project([unit])
    relations = {'SYNTAX_PARENT', 'HANDLER_OF', 'ENCLOSING_LOOP', 'IN_HANDLER', 'IN_TRY_BODY', 'CONTINUE_TARGET'}
    def context_facts(graph):
        return sorted((f.subject, f.relation, f.object) for f in graph.facts if f.relation in relations)
    assert context_facts(normal) == context_facts(reversed_graph)


def test_python_async_returned_attempt():
    source = SOURCES['python'].replace('def f', 'async def f').replace('return work()', 'return await work()')
    assert scan(source, 'python')
