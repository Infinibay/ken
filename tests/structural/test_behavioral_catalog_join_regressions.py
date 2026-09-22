"""Independent adversarial pairs for the behavioral catalog's occurrence joins.

The fixtures contain all the vocabulary of each pattern. Only the identity or
control-flow relationship changes. These are desired positive/negative oracles,
never snapshots of the detector's current answer.
"""
from __future__ import annotations

import pytest

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project

from .test_command_command_closure import SOURCES as COMMANDS
from .test_memento_serialized_snapshot import SOURCES as SNAPSHOTS
from .test_iterator_async_iterator import SOURCES as ASYNC
from .test_iterator_callback_iterator import source as callback_source
from .test_mediator_message_coordination import source as mediator_source
from .test_algorithm_chain_of_responsibility import source as chain_source
from .test_visitor_overloaded_dispatch import OVERLOADED


@pytest.fixture(scope='module')
def registry():
    return query_registry(builtin_rules())


def assert_detection(registry, target, language, text, expected):
    if language == 'python':
        compile(text, '<behavioral-regression>', 'exec')
    graph = link_project([lower_source(text, language, 'behavioral.' + language)])
    assert not graph.diagnostics, graph.diagnostics
    result = Engine(query_graph(graph), registry,
                    QueryBudget(max_matches=200, max_rows=500000, timeout_ms=3000),
                    'strict').execute(registry[target])
    assert result['complete'], result
    assert bool(result['matches']) is expected, (target, language, text, result)


LOGS = {
    'python': 'print(context)', 'javascript': 'console.log(context)',
    'typescript': 'console.log(context)', 'java': 'System.out.println(context)',
    'csharp': 'Console.WriteLine(context)', 'cpp': 'std::abs(context)',
    'go': 'println(context)', 'rust': 'std::hint::black_box(context)',
}


@pytest.mark.parametrize('language', COMMANDS)
@pytest.mark.parametrize('right_context', [True, False], ids=['positive', 'wrong-dispatch-input'])
def test_command_context_must_reach_the_queued_action_not_a_nearby_log(registry, language, right_context):
    text = COMMANDS[language][0]
    invocation = 'action.applyAsInt(context)' if language == 'java' else 'action(context)'
    # Last occurrence is invocation in run, never the Python closure declaration.
    before, found, after = text.rpartition(invocation)
    assert found
    called = invocation if right_context else invocation.replace('(context)', '(0)')
    separator = '\n            ' if language == 'python' else '; '
    text = before + called + separator + LOGS[language] + after
    if language == 'cpp':
        text = '#include <cstdlib>\n' + text
    assert_detection(registry, 'command#command-closure', language, text, right_context)


DECODERS = {
    'python': ('json.loads(payload)', 'json.loads("0")'),
    'javascript': ('JSON.parse(payload)', 'JSON.parse("0")'),
    'typescript': ('JSON.parse(payload)', 'JSON.parse("0")'),
    'java': ('gson.fromJson(payload, String.class)', 'gson.fromJson("0", String.class)'),
    'csharp': ('JsonSerializer.Deserialize<string>(payload)', 'JsonSerializer.Deserialize<string>("0")'),
    'cpp': ('decode(payload)', 'decode("0")'),
    'go': ('json.Unmarshal(payload, &e.state)', 'json.Unmarshal([]byte("0"), &e.state)'),
    'rust': ('serde_json::from_str(payload)', 'serde_json::from_str("0")'),
}

DISCARDED_SNAPSHOTS = {
    'python': ('return json.dumps(self.state)', 'json.dumps(self.state)\n        return "0"'),
    'javascript': ('return JSON.stringify(this.state);', 'JSON.stringify(this.state); return "0";'),
    'typescript': ('return JSON.stringify(this.state);', 'JSON.stringify(this.state); return "0";'),
    'java': ('return gson.toJson(this.state);', 'gson.toJson(this.state); return "0";'),
    'csharp': ('return JsonSerializer.Serialize(this.state);', 'JsonSerializer.Serialize(this.state); return "0";'),
    'cpp': ('return encode(state);', 'encode(state); return "0";'),
    'go': ('return json.Marshal(e.state)', 'json.Marshal(e.state)\n\treturn nil, nil'),
    'rust': ('serde_json::to_string(&self.state).unwrap()', 'serde_json::to_string(&self.state).unwrap(); "0".to_string()'),
}


@pytest.mark.parametrize('language', SNAPSHOTS)
@pytest.mark.parametrize('mode', ['positive', 'discards-encoded-state', 'decodes-unrelated-input'])
def test_serialized_memento_connects_both_public_snapshot_boundaries(registry, language, mode):
    text = SNAPSHOTS[language]
    if mode != 'positive':
        old, new = (DISCARDED_SNAPSHOTS if mode == 'discards-encoded-state' else DECODERS)[language]
        assert old in text
        text = text.replace(old, new)
    assert_detection(registry, 'memento#serialized-snapshot', language, text, mode == 'positive')


@pytest.mark.parametrize('language', ASYNC)
def test_async_iteration_allows_immediately_available_elements(registry, language):
    text = ASYNC[language]
    if language == 'python':
        text = text.replace('yield await fetch(index)', 'yield index')
    elif language == 'csharp':
        text = text.replace('yield return await Fetch(i);', 'yield return i;')
    else:
        text = text.replace('yield await fetch(i);', 'yield i;')
    assert_detection(registry, 'iterator#async-iterator', language, text, True)


@pytest.mark.parametrize('negated,exit_arm,expected', [
    (True, 'then', True), (False, 'else', True),
    (False, 'then', False), (True, 'else', False),
])
def test_go_range_callback_false_must_stop(registry, negated, exit_arm, expected):
    test = ('!' if negated else '') + '{callback}({element})'
    lines = ['if ' + test + ' {{', '\treturn', '}}'] if exit_arm == 'then' else [
        'if ' + test + ' {{', '\t{action}({element})', '}} else {{', '\treturn', '}}']
    assert_detection(registry, 'iterator#callback-iterator', 'go', callback_source(lines), expected)


@pytest.mark.parametrize('variant', ['message-coordination', 'tag-dispatch'])
@pytest.mark.parametrize('detached', [False, True], ids=['positive', 'self-sent-to-another-operation'])
def test_mediator_self_evidence_belongs_to_the_notification_call(registry, variant, detached):
    mode = 'positive' if variant == 'message-coordination' else 'no-tag-argument'
    text = mediator_source('python', mode)
    if detached:
        text = text.replace('self.coordinator.coordinate(self, tag)',
                            'self.coordinator.inspect(self)\n        self.coordinator.coordinate(None, tag)')
        text = text.replace('    def coordinate(self, origin, tag):',
                            '    def inspect(self, item): pass\n\n    def coordinate(self, origin, tag):')
    assert_detection(registry, 'mediator#' + variant, 'python', text, not detached)


@pytest.mark.parametrize('language', ['python', 'java', 'typescript'])
@pytest.mark.parametrize('noise_count', [0, 1, 20])
def test_chain_guard_return_allows_interleaved_independent_work(registry, language, noise_count):
    text = chain_source(language, 'early-handled')
    if language == 'python':
        marker = '        return self.following.handle(request)'
        noise = ''.join(f'        guard_noise_{i}=1+2\n' for i in range(noise_count))
    else:
        marker = 'return this.following.handle(request);'
        declaration = 'int' if language == 'java' else 'const'
        noise = ''.join(f'{declaration} guard_noise_{i}=1+2;' for i in range(noise_count))
    assert marker in text
    assert_detection(registry, 'chain-of-responsibility#linked-handlers', language,
                     text.replace(marker, noise + marker), True)


SAME_ELEMENT_OVERLOADS = {
    'java': '''interface ShapeVisitor { void visit(Circle c); void visit(Circle c, int metadata); }
class Circle { void accept(ShapeVisitor visitor) { visitor.visit(this); } }''',
    'csharp': '''interface ShapeVisitor { void Visit(Circle c); void Visit(Circle c, int metadata); }
class Circle { void Accept(ShapeVisitor visitor) { visitor.Visit(this); } }''',
    'cpp': '''class Circle;
class ShapeVisitor { public: virtual void visit(Circle& c)=0; virtual void visit(Circle& c, int metadata)=0; };
class Circle { public: void accept(ShapeVisitor& visitor) { visitor.visit(*this); } };''',
}


@pytest.mark.parametrize('language', OVERLOADED)
@pytest.mark.parametrize('different_elements', [True, False], ids=['positive', 'same-element-overloads'])
def test_visitor_overloads_dispatch_across_distinct_element_types(registry, language, different_elements):
    text = (OVERLOADED if different_elements else SAME_ELEMENT_OVERLOADS)[language]
    assert_detection(registry, 'visitor#overloaded-dispatch', language, text, different_elements)


@pytest.mark.parametrize('qualifier,expected', [('P', True), ('Fixed', False)])
@pytest.mark.parametrize('noise', ['', 'int unrelated=1+2;'])
def test_static_strategy_can_dispatch_by_type_without_an_instance_field(registry, qualifier, expected, noise):
    text = f'''struct Fixed {{ static int apply(int x) {{ return x+1; }} }};
template<class P> struct Algorithm {{
 int run(int x) {{ {noise} return {qualifier}::apply(x); }}
}};'''
    assert_detection(registry, 'strategy#static-policy', 'cpp', text, expected)
