"""Iterator ``callback-iterator``: a push iterator whose callback governs stopping.

The variant is a published rule, so the test goes through the registry name
``iterator#callback-iterator`` rather than a private copy of the query.

Nothing new was needed in the IR: the callback parameter is already a callee
(``CALLEE_VALUE``), the branch already records what it tests (``TRUTH_TEST``) and the
loop already links its element (``ITERATION_BINDING``). What this file pins down is
the **join** between them, which is where the query went wrong first.

``ARGUMENT`` in KenQL does not bind the argument's storage. It binds a synthetic
occurrence node, ``<call>/argument/<position>``, and reaches the value through
``VALUE`` and then ``LOADED_FROM``. The obvious
``require $call ARGUMENT $element`` therefore compares a call-site occurrence against
a loop binding and joins on nothing, silently returning no matches rather than
failing. ``test_the_element_link_is_storage_identity_not_a_call_site_occurrence``
holds that chain down.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.kenql import query_graph
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'iterator#callback-iterator'
LANGUAGES = ['go']


def variant():
    rule = next(r for r in _load_catalog() if r.id == 'iterator')
    return next(v for v in rule.variants if v['id'] == 'callback-iterator')


def source(lines, names=None):
    names = names or {'iterator': 'Each', 'callback': 'yield', 'collection': 'values',
                      'element': 'value', 'action': 'consume'}
    return ('package seq\n\n'
            f'func {names["iterator"]}({names["collection"]} []int, {names["callback"]} func(int) bool) {{\n'
            f'\tfor _, {names["element"]} := range {names["collection"]} {{\n'
            + ''.join('\t\t' + line.format(**names) + '\n' for line in lines)
            + '\t}\n}\n')


def detect(src):
    graph = link_project([lower_source(src, 'go', 'iterator.go')])
    assert not graph.diagnostics, graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(RULE, registry)], registry=registry,
                           evidence_mode='strict')
    assert result['complete'], result['outcomes']
    return result['matches']


def test_push_iterator_with_a_governing_callback_is_detected():
    src = source(['if !{callback}({element}) {{', '\treturn', '}}'])
    matches = detect(src)
    assert len(matches) == 1
    bindings = matches[0]['bindings']
    assert '/CALLABLE:Each' in bindings['$iterator']
    assert '/PARAMETER:yield' in bindings['$callback']
    assert '/STORAGE:value' in bindings['$element']
    assert bindings['$call'] != bindings['$element']
    assert bindings['$branch'] != bindings['$exit']


def test_renamed_identifiers_preserve_detection():
    src = source(['if !{callback}({element}) {{', '\treturn', '}}'],
                 names={'iterator': 'Walk', 'callback': 'emit', 'collection': 'items',
                        'element': 'item', 'action': 'consume'})
    assert detect(src)


@pytest.mark.parametrize('label,lines', [
    ('negated-return', ['if !{callback}({element}) {{', '\treturn', '}}']),
    ('negated-break', ['if !{callback}({element}) {{', '\tbreak', '}}']),
    ('else-return', ['if {callback}({element}) {{', '\t{action}({element})', '}} else {{', '\treturn', '}}']),
])
def test_every_stopping_spelling_is_admitted(label, lines):
    """The polarity is not the contract; that the boolean stops the loop is."""
    assert detect(source(lines)), label


def test_a_callback_whose_result_is_never_tested_is_rejected():
    assert not detect(source(['{callback}({element})']))


def test_a_callback_that_receives_a_constant_is_rejected():
    assert not detect(source(['if !{callback}(0) {{', '\treturn', '}}']))


def test_a_callback_that_receives_another_value_is_rejected():
    assert not detect(source(['other := 1', 'if !{callback}(other) {{', '\treturn', '}}']))


def test_a_branch_testing_an_unrelated_call_is_rejected():
    assert not detect(source(['{callback}({element})', 'if isDone() {{', '\treturn', '}}']))


def test_a_branch_testing_an_unrelated_value_is_rejected():
    assert not detect(source(['{callback}({element})', 'if {element} > 0 {{', '\treturn', '}}']))


def test_a_callback_that_is_never_called_is_rejected():
    assert not detect(source(['{action}({element})']))


def test_a_tested_callback_whose_outcome_does_not_stop_is_rejected():
    """Testing the result is not enough: the branch has to end the iteration."""
    assert not detect(source(['if !{callback}({element}) {{', '\t{action}({element})', '}}']))


def test_variant_declares_its_language_as_ready():
    row = variant()
    assert row['languages'] == LANGUAGES
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'TRUTH_TEST' in row['query'] and 'ITERATION_BINDING' in row['query']


def test_the_element_link_is_storage_identity_not_a_call_site_occurrence():
    """``ARGUMENT`` binds ``<call>/argument/<n>``; ``LOADED_FROM`` reaches the slot.

    Joining ``ITERATION_BINDING`` straight onto the ``ARGUMENT`` object compares a
    call-site occurrence with a loop binding and matches nothing, which looks like a
    simply absent pattern rather than a broken query.
    """
    graph = link_project([lower_source(source(['if !{callback}({element}) {{', '\treturn', '}}']),
                                       'go', 'iterator.go')])
    # The projection lives in the query view, not in the source IR: there an
    # ARGUMENT points straight at the storage, which is exactly why the wrong join
    # looks plausible when read off the source graph.
    view = query_graph(graph).ir
    arguments = {f.object for f in view.facts if f.relation == 'ARGUMENT'}
    bindings = {f.object for f in view.facts if f.relation == 'ITERATION_BINDING'}
    assert arguments, 'the fixture must call the callback'
    assert bindings, 'the fixture must bind a loop element'
    assert not arguments & bindings, (arguments, bindings)
    # argument -> VALUE -> loaded-value -> LOADED_FROM -> the loop's storage slot.
    values = {f.subject: f.object for f in view.facts
              if f.relation == 'VALUE' and f.subject in arguments}
    loaded = {f.subject: f.object for f in view.facts if f.relation == 'LOADED_FROM'}
    reached = {loaded[v] for v in values.values() if v in loaded}
    assert reached & bindings, (values, loaded, bindings)
