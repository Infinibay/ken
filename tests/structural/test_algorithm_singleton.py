"""Singleton usage/scope contracts beyond the existing null-polarity matrices."""
from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import SavedRule, builtin_rules, execute_rules
from ken.structural.semantic import link_project

from .test_gof_executable import evaluate
from .test_lazy_null_flow import source as lazy_source

LANGUAGES = ('python', 'java', 'typescript')


def scoped_source(language: str, *, correct_usage: bool = True) -> str:
    text = lazy_source(language)
    # Same slot spelling and same nominal accessor shape in another owner must
    # not satisfy an invocation of the selected lazy type.
    text += lazy_source(language, 'fresh-return').replace('Shared', 'Other')
    target = 'Shared' if correct_usage else 'Other'
    if language == 'python':
        return text + f'''\ndef client():
    audit = 17 * 3
    print(audit)
    result = {target}.get()
    independent = 9 + 1
    print(independent)
    return result
'''
    if language == 'java':
        return text + f'''class Client {{
    Object obtain() {{
        int audit = 17 * 3; System.out.println(audit);
        Object result = {target}.get();
        int independent = 9 + 1; System.out.println(independent);
        return result;
    }}
}}
'''
    return text + f'''function client() {{
    const audit = 17 * 3; console.log(audit);
    const result = {target}.get();
    const independent = 9 + 1; console.log(independent);
    return result;
}}
'''


def usages(text: str, language: str):
    graph = link_project([lower_source(text, language, 'singleton-usage')])
    assert not graph.diagnostics
    registry = builtin_rules()
    query = SavedRule('observed_lazy_use', '''query observed_lazy_use {
      match "singleton.lazy_instance"(unit:$unit, storage:$storage, accessor:$accessor, creation:$creation);
      require $call TARGET $accessor;
      emit $unit, $storage, $accessor, $creation, $call;
    }''')
    result = execute_rules(graph, [query], registry=registry)
    assert result['complete']
    return graph, result['matches']


@pytest.mark.parametrize('language,correct_usage', [
    pytest.param('python', True, marks=pytest.mark.xfail(strict=True, reason='Python classmethod call target resolution is not modeled by direct-class-static')),
    ('java', True), ('typescript', True),
    ('python', False), ('java', False), ('typescript', False),
])
def test_named_usage_keeps_called_owner_and_storage_scope(language, correct_usage):
    graph, matches = usages(scoped_source(language, correct_usage=correct_usage), language)
    assert bool(matches) == correct_usage
    if matches:
        assert {graph.entities[m['bindings']['$unit']].name for m in matches} == {'Shared'}


@pytest.mark.parametrize('language', LANGUAGES)
def test_unsynchronized_accessor_is_only_a_candidate(language):
    # A positive lexical candidate is intentionally not a thread-safety proof.
    assert evaluate(lazy_source(language), language, 'singleton')


def with_local_work(language: str, position: str) -> str:
    text = lazy_source(language)
    if language == 'python':
        if position == 'before-guard':
            return text.replace('  if cls.value', '  audit = 17 * 3\n  if cls.value')
        return text.replace('  return cls.value', '  audit = 17 * 3\n  return cls.value')
    work = 'int audit = 17 * 3;' if language == 'java' else 'const audit = 17 * 3;'
    if position == 'before-guard':
        return text.replace('if(Shared.value', work + 'if(Shared.value')
    return text.replace('return Shared.value;', work + 'return Shared.value;')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('position', ['before-guard', 'before-return'])
@pytest.mark.xfail(strict=True, reason='Lazy query requires immediate CFG entry/return adjacency even across pure independent arithmetic; algorithms/singleton.md')
def test_desired_lazy_algorithm_tolerates_pure_local_arithmetic(language, position):
    assert evaluate(with_local_work(language, position), language, 'singleton')
