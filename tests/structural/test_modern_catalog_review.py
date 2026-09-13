"""Executable review of all modern concepts, plus opt-in retention precision."""
import pytest

from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule, select_rules
from ken.structural.semantic import link_project

from .test_adapted_continuation import SOURCES as ADAPTED
from .test_cache_aside_flow import source as cache_source
from .test_closure_ownership import WRAPPERS
from .test_dispatch_table import SOURCES as DISPATCH
from .test_exception_retry import SOURCES as RETRY
from .test_modern_patterns import SOURCES as INJECTION
from .test_queued_commands import source as queue_source
from .test_read_through_cache import source as read_source
from .test_subclass_factories import source as subclass_source
from .test_unit_of_work import source as work_source


LANGUAGES = ['python', 'javascript', 'typescript']
CONCEPTS = ['continuation-wrapper', 'adapted-continuation-wrapper', 'dependency-injection',
            'dispatch-table', 'exception-retry', 'subclass-factory', 'cache-aside',
            'read-through-cache', 'batch-work-queue', 'unit-of-work']


def rule_id(concept):
    prefix = 'resilience' if concept == 'exception-retry' else 'persistence' if concept == 'unit-of-work' else 'architecture'
    return prefix + '.' + concept


def scan(text, language, rule):
    graph = link_project([lower_source(text, language, 'modern-review')])
    assert not graph.diagnostics
    registry = builtin_rules()
    result = execute_rules(graph, [named_rule(rule, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


def fixture(concept, language, negative=False):
    if concept == 'continuation-wrapper':
        text = WRAPPERS[language]
        return text.replace('next(x)', 'other(x)') if negative else text
    if concept == 'adapted-continuation-wrapper':
        text = ADAPTED[language]
        return text.replace('next.handle', 'other.handle') if negative else text
    if concept == 'dependency-injection':
        text = INJECTION[language]
        return text.replace('dependency.run', 'other.run') if negative else text
    if concept == 'dispatch-table':
        text = DISPATCH[language]
        return text.replace('table[requested]', 'other[requested]') if negative else text
    if concept == 'exception-retry':
        text = RETRY[language]
        return text.replace('continue', 'break') if negative else text
    if concept == 'subclass-factory':
        return subclass_source(language, 'other-return' if negative else 'positive')
    if concept == 'cache-aside':
        return cache_source(language, 'value-after-load' if negative else 'positive')
    if concept == 'read-through-cache':
        return read_source(language, 'other-write-value' if negative else 'positive')
    if concept == 'batch-work-queue':
        return queue_source(language, 'other-item' if negative else 'positive')
    text = work_source(language)
    return text.replace('store.delete(item)', 'store.delete(other)') if negative else text


@pytest.mark.parametrize('concept', CONCEPTS)
@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('negative', [False, True])
@pytest.mark.parametrize('surrounding_work', [False, True])
def test_all_modern_concepts_have_source_witnesses_and_contrasts(concept, language, negative, surrounding_work):
    text = fixture(concept, language, negative)
    if surrounding_work:
        # Additional independent code, explicitly not proof of arbitrary harmless
        # statements interleaved inside the matched algorithm.
        text += '\ndef audit_metric():\n return 2+3\n' if language == 'python' else '\nfunction audit_metric(){return 2+3;}'
    assert bool(scan(text, language, rule_id(concept))) is not negative


def test_all_ten_public_rules_and_ready_children_are_executable():
    registry = builtin_rules()
    modern = select_rules(registry, collections=['modern'])
    assert {r.id for r in modern} == {rule_id(c) for c in CONCEPTS}
    for rule in modern:
        rule.validate()
        assert rule.query.strip().startswith('query ')
        assert 'require ' in rule.query or 'match ' in rule.query
        for child in [*rule.variants, *rule.operations]:
            if child['status'] == 'ready':
                assert 'require ' in child['query'] or 'match ' in child['query']


@pytest.mark.parametrize('language', list(INJECTION))
@pytest.mark.parametrize('change', ['positive', 'noise', 'input-rebound', 'field-overwritten'])
def test_opt_in_retained_object_contract(language, change):
    text = INJECTION[language]
    py = language == 'python'
    assignment = 'self.dependency = incoming' if py else 'this.dependency = incoming;'
    if change == 'input-rebound':
        text = text.replace(assignment, ('incoming=None;' if py else 'incoming=null;') + assignment)
    elif change == 'field-overwritten':
        text = text.replace(assignment, assignment + (';self.dependency=None' if py else 'this.dependency=null;'))
    elif change == 'noise':
        noise = 'metric=2+3;' if py else 'let metric=2+3;' if language in {'javascript','typescript'} else 'int metric=2+3;'
        text = text.replace(assignment, noise + assignment)
    result = scan(text, language, 'architecture.dependency-injection#retained-object')
    assert bool(result) is (change in {'positive', 'noise'})


@pytest.mark.parametrize('language', ['python', 'javascript', 'typescript'])
def test_base_injection_still_accepts_conditional_configuration(language):
    text = INJECTION[language]
    assignment = 'self.dependency = incoming' if language == 'python' else 'this.dependency = incoming;'
    # This shape is intentionally outside the strict summary. Use a branch whose
    # assignment remains explicit so historical supply/use evidence still exists.
    replacement = '\n  if incoming: self.dependency = incoming' if language == 'python' else 'if(incoming){this.dependency = incoming;}'
    text = text.replace(assignment, replacement)
    assert scan(text, language, 'architecture.dependency-injection')
    assert not scan(text, language, 'architecture.dependency-injection#retained-object')


@pytest.mark.parametrize('language', list(INJECTION))
def test_opt_in_retention_accepts_constructor_injection(language):
    text = INJECTION[language]
    if language == 'python':
        text = text.replace('configure', '__init__')
    elif language in {'java', 'csharp'}:
        text = text.replace('void configure', 'Consumer')
    else:
        text = text.replace('configure', 'constructor').replace('): void { this.dependency', ') { this.dependency')
    assert scan(text, language, 'architecture.dependency-injection#retained-object')
