"""Bridge algorithm flow refinements; nominal hierarchy tests live elsewhere."""
import pytest

from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from .test_refined_bridge import detect, source


LANGUAGES = ['python', 'java', 'typescript']
RETURNED_PRIMITIVE = '''query bridge_returned_primitive {
 match "bridge#refined-composition"(unit:$unit,operation:$operation,access:$access);
 require $operation HAS_OPERATION $return;
 require $return RETURN_ORIGIN $call;
 require $call RECEIVER $access;
 emit $unit,$operation,$call;
}'''


def body(language, statements):
    text = source(language)
    if language == 'python':
        old = ' def render(self): return self.driver.run()'
        new = ' def render(self):\n' + ''.join('  ' + statement + '\n' for statement in statements)
    else:
        old = 'return this.driver.run();'
        new = ';'.join(statements) + ';'
    assert old in text
    return text.replace(old, new)


def statements(language, mutation='positive'):
    receiver = 'self' if language == 'python' else 'this'
    declaration = '' if language == 'python' else 'int ' if language == 'java' else 'let '
    result = [f'{declaration}value = {receiver}.driver.run()']
    result += ['metric = 1 + 2', 'print(metric)'] if language == 'python' else [f'{declaration}metric = 1 + 2', 'System.out.println(metric)' if language == 'java' else 'console.log(metric)']
    if mutation == 'discard':
        result += ['return 0']
    elif mutation == 'overwritten':
        result += ['value = 0', 'return value']
    elif mutation == 'saved':
        result += [f'{declaration}saved = value', 'value = 0', 'return saved']
    else:
        result += ['return value']
    return result


def refined(text, language):
    graph, result = detect(text, language)
    assert result['matches'], 'The flow refinement must not erase the valid nominal definition'
    result = execute_rules(graph, [SavedRule('bridge-returned-primitive', RETURNED_PRIMITIVE)], registry=builtin_rules())
    assert result['complete'], result['outcomes']
    return result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mode', ['positive', 'saved'])
def test_backend_result_survives_noise_and_alias_rebinding(language, mode):
    text = body(language, statements(language, mode))
    assert refined(text, language)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['discard', 'overwritten'])
def test_return_flow_refinement_rejects_discarded_backend_result(language, mutation):
    text = body(language, statements(language, mutation))
    assert not refined(text, language)


@pytest.mark.parametrize('language', LANGUAGES)
def test_fixed_backend_receiver_is_not_retained_implementation(language):
    steps = statements(language)
    steps[0] = steps[0].replace('self.driver.run()', 'First().run()').replace('this.driver.run()', 'new First().run()')
    _, result = detect(body(language, steps), language)
    assert not result['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_field_replacement_makes_return_origin_analysis_unsupported(language):
    assignment = 'self.driver = First()' if language == 'python' else 'this.driver = new First()'
    text = body(language, [assignment, *statements(language)])
    assert not refined(text, language)
    graph, result = detect(text, language)
    operations = {m['bindings']['$operation'] for m in result['matches']}
    assert all(any(f.subject == operation and f.relation == 'RETURN_FLOW_STATUS' and f.object == 'unsupported' for f in graph.facts) for operation in operations)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.xfail(strict=True, reason='Injected-backend refinement does not correlate constructor input with stored implementation')
def test_requested_injected_backend_contract_rejects_ignored_selection(language):
    text = body(language, statements(language))
    text = text.replace('self.driver:Driver=driver', 'self.driver:Driver=First()').replace('this.driver=driver;', 'this.driver=new First();')
    # A fixed-backend Bridge definition can remain valid. This is specifically
    # the still-missing contract that the supplied constructor input is used.
    assert not refined(text, language)
