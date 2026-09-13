"""State actions install successors through the context's state setter.

Own source fixtures are parsed, never executed; negative mutations remove a
specific correlation without relying on names or upstream directory labels.
"""
import re

import pytest

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import builtin_rules, named_rule, execute_rules


LANGUAGES = ['python', 'javascript', 'typescript', 'java', 'csharp']


def source(language, mutation='positive', parameter_property=False):
    if language == 'python':
        text = '''class State:
 def act(self): pass
class Context:
 state: State
 other: State
 def __init__(self, other):
  self.state = Idle(self)
 def request(self):
  self.state.act()
 def install(self, candidate: State):
  self.state = candidate
class Idle(State):
 ctx: Context
 other: Context
 def __init__(self, ctx: Context):
  self.ctx = ctx
 def act(self):
  self.ctx.install(Ready())
 def inspect(self): pass
class Ready(State):
 def act(self): pass
class Foreign: pass
'''
        changes = {
            'no-dispatch': ('self.state.act()', 'self.state.inspect()'),
            'wrong-slot': ('self.state = candidate', 'self.other = candidate'),
            'constant-setter': ('self.state = candidate', 'self.state = None'),
            'setter-rebound': ('self.state = candidate', 'candidate = None\n  self.state = candidate'),
            'setter-overwritten': ('self.state = candidate', 'self.state = candidate\n  self.state = None'),
            'abandoned': ('self.ctx.install(Ready())', 'Ready()'),
            'other-context': ('self.ctx.install(Ready())', 'self.other.install(Ready())'),
            'not-installed': ('self.state = Idle(self)', 'self.other = Idle(self)'),
            'wrong-successor': ('self.ctx.install(Ready())', 'self.ctx.install(Foreign())'),
            'unrelated-action': ('self.ctx.install(Ready())\n def inspect(self): pass', 'pass\n def inspect(self):\n  self.ctx.install(Ready())'),
            'constructor-overwritten': ('self.ctx = ctx', 'self.ctx = ctx\n  self.ctx = None'),
            'different-initial-context': ('Idle(self)', 'Idle(other)'),
            'guarded-transition': ('self.ctx.install(Ready())', 'if self.ctx is not None:\n   self.ctx.install(Ready())'),
        }
    else:
        js = language == 'javascript'
        ts = language == 'typescript'
        java = language == 'java'
        if js or ts:
            contract = 'class State { act() {} }' if js else 'interface State { act(): void; }'
            context_fields = '' if js else 'state: State; other: State;'
            state_fields = '' if js else 'ctx: Context; other: Context;'
            context_ctor = 'constructor(other)' if js else 'constructor(other: Context)'
            state_ctor = 'constructor(ctx)' if js else 'constructor(ctx: Context)'
            setup = 'super(); this.ctx = ctx;' if js else 'this.ctx = ctx;'
            heritage = 'extends' if js else 'implements'
            setter = 'install(candidate)' if js else 'install(candidate: State)'
            method = 'act()'
            if parameter_property:
                state_fields = 'other: Context;'
                state_ctor = 'constructor(public ctx: Context)'
                setup = ''
        else:
            contract = 'interface State { ' + ('void act();' if java else 'void act();') + ' }'
            context_fields = 'State state; State other;'
            state_fields = 'Context ctx; Context other;'
            context_ctor = 'public Context(Context other)'
            state_ctor = 'public Idle(Context ctx)'
            setup = 'this.ctx = ctx;'
            heritage = 'implements' if java else ':'
            setter = 'public void install(State candidate)'
            method = 'public void act()'
        request = 'request()' if js or ts else 'public void request()'
        inspect = 'inspect()' if js or ts else 'public void inspect()'
        text = f'''{contract}
class Context {{ {context_fields}
 {context_ctor} {{ this.state = new Idle(this); }}
 {request} {{ this.state.act(); }}
 {setter} {{ this.state = candidate; }}
}}
class Idle {heritage} State {{ {state_fields}
 {state_ctor} {{ {setup} }}
 {method} {{ this.ctx.install(new Ready()); }}
 {inspect} {{ }}
}}
class Ready {heritage} State {{ {method} {{ }} }}
class Foreign {{ }}
'''
        changes = {
            'no-dispatch': ('this.state.act()', 'this.state.inspect()'),
            'wrong-slot': ('this.state = candidate;', 'this.other = candidate;'),
            'constant-setter': ('this.state = candidate;', 'this.state = null;'),
            'setter-rebound': ('this.state = candidate;', 'candidate = null; this.state = candidate;'),
            'setter-overwritten': ('this.state = candidate;', 'this.state = candidate; this.state = null;'),
            'abandoned': ('this.ctx.install(new Ready());', 'new Ready();'),
            'other-context': ('this.ctx.install(new Ready());', 'this.other.install(new Ready());'),
            'not-installed': ('this.state = new Idle(this);', 'this.other = new Idle(this);'),
            'wrong-successor': ('this.ctx.install(new Ready());', 'this.ctx.install(new Foreign());'),
            'unrelated-action': (f'{method} {{ this.ctx.install(new Ready()); }}\n {inspect} {{ }}', f'{method} {{ }}\n {inspect} {{ this.ctx.install(new Ready()); }}'),
            'constructor-overwritten': (f'{state_ctor} {{ {setup} }}', f'{state_ctor} {{ {setup} this.ctx = null; }}'),
            'different-initial-context': ('new Idle(this)', 'new Idle(other)'),
            'guarded-transition': ('this.ctx.install(new Ready());', 'if (this.ctx != null) { this.ctx.install(new Ready()); }'),
        }
    if mutation in changes:
        old, new = changes[mutation]
        assert old in text
        text = text.replace(old, new)
    if mutation == 'renamed':
        for a, b in [('Context','Session'),('Idle','First'),('Ready','Second'),('State','Protocol'),('act','advance'),('install','replace'),('state','mode'),('ctx','owner')]:
            text = re.sub(r'\b'+a+r'\b', b, text)
    return text


def detect(text, language):
    graph = link_project([lower_source(text, language, 'state-example')])
    assert not graph.diagnostics
    rules = builtin_rules()
    out = execute_rules(graph, [named_rule('state#context-transition', rules)], registry=rules)
    assert out['complete'], out
    return graph, out


CASES = ['positive', 'renamed', 'guarded-transition', 'no-dispatch', 'wrong-slot',
         'constant-setter', 'setter-rebound', 'setter-overwritten', 'abandoned',
         'other-context', 'not-installed', 'wrong-successor', 'unrelated-action',
         'constructor-overwritten', 'different-initial-context']


@pytest.mark.parametrize('language,property', [(lang, False) for lang in LANGUAGES] + [('typescript', True)])
@pytest.mark.parametrize('mutation', CASES)
def test_context_transition_requires_the_correlated_path(language, property, mutation):
    _, out = detect(source(language, mutation, property), language)
    assert bool(out['matches']) == (mutation in {'positive', 'renamed', 'guarded-transition'}), out


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('swapped', [False, True])
def test_initial_constructor_binding_cannot_borrow_another_arguments_context(language, swapped):
    text = source(language)
    if language == 'python':
        text = text.replace('Idle(self)', 'Idle(other, self)' if swapped else 'Idle(self, other)')
        text = text.replace('def __init__(self, ctx: Context):', 'def __init__(self, ctx: Context, ignored: Context):')
    else:
        text = text.replace('new Idle(this)', 'new Idle(other, this)' if swapped else 'new Idle(this, other)')
        old = {'javascript': 'constructor(ctx)', 'typescript': 'constructor(ctx: Context)',
               'java': 'public Idle(Context ctx)', 'csharp': 'public Idle(Context ctx)'}[language]
        new = {'javascript': 'constructor(ctx, ignored)', 'typescript': 'constructor(ctx: Context, ignored: Context)',
               'java': 'public Idle(Context ctx, Context ignored)', 'csharp': 'public Idle(Context ctx, Context ignored)'}[language]
        assert old in text
        text = text.replace(old, new)
    _, out = detect(text, language)
    assert bool(out['matches']) != swapped


@pytest.mark.parametrize('language', ['python', 'typescript', 'java', 'csharp'])
@pytest.mark.parametrize('swapped', [False, True])
def test_setter_argument_position_is_correlated_with_its_written_parameter(language, swapped):
    text = source(language)
    if language == 'python':
        text = text.replace('install(self, candidate: State)', 'install(self, candidate: State, ignored: State)')
        text = text.replace('install(Ready())', 'install(None, Ready())' if swapped else 'install(Ready(), None)')
    else:
        old = 'install(candidate: State)' if language == 'typescript' else 'install(State candidate)'
        new = 'install(candidate: State, ignored: State)' if language == 'typescript' else 'install(State candidate, State ignored)'
        text = text.replace(old, new)
        text = text.replace('install(new Ready())', 'install(null, new Ready())' if swapped else 'install(new Ready(), null)')
    _, out = detect(text, language)
    assert bool(out['matches']) != swapped


@pytest.mark.parametrize('replacement', [
    'this.ctx.other(new Ready())', 'this.ctx.install(...[new Ready()])',
    'this.ctx.install(makeReady())', 'this.ctx.install(null)',
])
def test_dynamic_transition_requires_direct_positional_construction(replacement):
    _, out = detect(source('javascript').replace('this.ctx.install(new Ready())', replacement), 'javascript')
    assert not out['matches']


def test_dynamic_transition_does_not_guess_multi_parameter_setter():
    text = source('javascript').replace('install(candidate)', 'install(candidate, ignored)')
    _, out = detect(text, 'javascript')
    assert not out['matches']
