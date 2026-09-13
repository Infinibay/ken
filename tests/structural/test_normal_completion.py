"""Normal statement paths are distinct from runtime reachability and exception CFG."""
from textwrap import indent

import pytest

from ken.structural import IR, lower_source, link_project
from ken.structural.rules import builtin_rules, execute_rules, named_rule


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp', 'cpp']


def source(language, handler, *, tail='', do=False):
    if language == 'python':
        return 'def f():\n while True:\n  try:\n   return work()\n  except Error:\n' + indent(handler, '   ') + '\n' + indent(tail, '  ') + '\n'
    catches = {'java': 'Exception e', 'csharp': 'Exception e', 'cpp': '...',
               'javascript': 'e', 'typescript': 'e'}
    headers = {'java': 'class C { Object f()', 'csharp': 'class C { object f()',
               'cpp': 'int f()', 'javascript': 'function f()', 'typescript': 'function f()'}
    loop = 'try{return work();}catch(' + catches[language] + '){' + handler + '}' + tail
    loop = 'do {' + loop + '} while(true);' if do else 'while(true){' + loop + '}'
    return headers[language] + '{' + loop + '}' + ('}' if language in {'java', 'csharp'} else '')


HANDLERS = {
    'empty': ('pass', '', 'possible'),
    'call': ('pause()', 'pause();', 'possible'),
    'conditional-stop': ('if stop:\n raise Error()', 'if(stop){throw error;}', 'possible'),
    'two-normal-arms': ('if stop:\n pause()\nelse:\n trace()', 'if(stop){pause();}else{trace();}', 'possible'),
    'return': ('return 1', 'return 1;', 'abrupt'),
    'throw': ('raise Error()', 'throw error;', 'abrupt'),
    'break': ('break', 'break;', 'abrupt'),
    'continue': ('continue', 'continue;', 'abrupt'),
    'both-abrupt': ('if stop:\n return 1\nelse:\n raise Error()', 'if(stop){return 1;}else{throw error;}', 'abrupt'),
    'unreachable-call': ('return 1\npause()', 'return 1;pause();', 'abrupt'),
    'unsupported-loop': ('while stop:\n break', 'while(stop){break;}', 'unsupported'),
}


def build(text, language):
    unit = lower_source(text, language, 'sample')
    assert not unit.diagnostics, unit.diagnostics
    return IR.from_dict(link_project([unit]).to_dict())


def matches(graph):
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule('resilience.exception-retry#handler-fallthrough', registry)], registry=registry)
    assert result['complete'], result
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('case', HANDLERS)
def test_handler_paths(language, case):
    py, other, expected = HANDLERS[case]
    graph = build(source(language, py if language == 'python' else other), language)
    handler = next(o for o in graph.operations if o.native_kind in {'except_clause', 'catch_clause'})
    state = next(f.object for f in graph.facts if f.subject == handler.id and f.relation == 'NORMAL_COMPLETION')
    assert state == expected
    assert bool(matches(graph)) == (expected == 'possible')
    assert any(f.relation == 'CFG_STATUS' and f.object == 'partial' for f in graph.facts)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('tail', ['return', 'call'])
def test_try_must_be_the_direct_loop_tail(language, tail):
    suffix = ('return 1' if tail == 'return' else 'other()') + ('' if language == 'python' else ';')
    graph = build(source(language, 'pass' if language == 'python' else '', tail=suffix), language)
    assert not matches(graph)


@pytest.mark.parametrize('language', LANGUAGES)
def test_nested_protected_wait(language):
    catch = {'javascript':'x', 'typescript':'x', 'java':'Exception x', 'csharp':'Exception x', 'cpp':'...'}
    handler = 'try:\n pause()\nexcept Error:\n pass' if language == 'python' else 'try{pause();}catch('+catch[language]+'){}'
    assert matches(build(source(language, handler), language))


@pytest.mark.parametrize('language', LANGUAGES[1:])
@pytest.mark.parametrize('explicit', [True, False])
def test_do_while_has_loop_identity_and_context(language, explicit):
    graph = build(source(language, 'continue;' if explicit else 'pause();', do=True), language)
    loop = next(o for o in graph.operations if o.native_kind == 'do_statement')
    assert loop.kind == 'LOOP'
    assert any(f.relation == 'ENCLOSING_LOOP' and f.object == loop.id for f in graph.facts)
    if explicit:
        assert any(f.relation == 'CONTINUE_TARGET' and f.object == loop.id for f in graph.facts)
    else:
        assert matches(graph)


@pytest.mark.parametrize('otherwise', [False, True])
def test_python_elif_chain_preserves_final_else(otherwise):
    handler = 'if first:\n return 1\nelif second:\n raise Error()'
    if otherwise: handler += '\nelse:\n return 2'
    assert bool(matches(build(source('python', handler), 'python'))) is not otherwise


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript', 'java', 'csharp'])
def test_finally_is_not_a_proven_handler_continuation(language):
    text = source(language, 'pass' if language == 'python' else 'pause();')
    if language == 'python': text += '  finally:\n   return 1\n'
    else: text = text.replace('pause();}', 'pause();}finally{return 1;}')
    assert not matches(build(text, language))


def test_python_try_else_is_not_a_plain_handler_continuation():
    text = source('python', 'pass') + '  else:\n   return 1\n'
    assert not matches(build(text, 'python'))


def test_java_resource_cleanup_is_not_assumed_to_complete():
    text = source('java', '').replace('try{', 'try(Resource resource=open()){')
    assert not matches(build(text, 'java'))


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
def test_suspended_handler_is_unsupported(language):
    text = source(language, 'await pause()' + ('' if language == 'python' else ';'))
    text = text.replace('def f', 'async def f').replace('function f', 'async function f')
    assert not matches(build(text, language))


def test_fact_order_does_not_change_nested_completion():
    text = source('python', 'if first:\n pause()\nelse:\n raise Error()')
    unit = lower_source(text, 'python', 'sample')
    original = link_project([unit])
    unit.operations.reverse()
    reverse = link_project([unit])
    def facts(graph):
        return sorted((f.subject, f.relation, f.object) for f in graph.facts
                      if f.relation in {'NORMAL_COMPLETION', 'LOOP_BODY_TAIL', 'HANDLER_FALLTHROUGH'})
    assert facts(original) == facts(reverse)
