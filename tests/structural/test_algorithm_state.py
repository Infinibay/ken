"""Event-driven state transitions and temporal owner/dispatch refinements."""
from __future__ import annotations

import pytest

from .test_state_context_transitions import detect, source as context_source

LANGUAGES = ('python', 'java', 'typescript')


def source(language: str, mutation: str = '', noise: bool = True) -> str:
    text = context_source(language)
    if language == 'python':
        text = text.replace('def request(self):', 'def request(self, event):')
        text = text.replace('def act(self):', 'def act(self, event):')
        text = text.replace('self.state.act()', 'self.state.act(event)')
        action = '  self.ctx.install(Ready())'
        prefix = '  audit=17*3\n  print(audit)\n' if noise else ''
        replacement = prefix + '  if event > 0:\n   self.ctx.install(Ready())'
        if mutation == 'different-current-context':
            replacement = '  self.ctx=Context(None)\n' + replacement
        text = text.replace(action, replacement)
        if noise:
            text = text.replace('  self.state = candidate', '  independent=9+1\n  print(independent)\n  self.state = candidate')
        if mutation == 'wrong-event':
            text = text.replace('self.state.act(event)', 'self.state.act(0)')
        if mutation == 'wrong-transition-slot':
            text = text.replace('self.state = candidate', 'self.other = candidate')
        if mutation == 'current-state-replaced':
            text = text.replace('  self.state.act(event)', '  self.state=Ready()\n  self.state.act(event)')
    else:
        if language == 'java':
            text = text.replace('void request()', 'void request(int event)')
            text = text.replace('void act()', 'void act(int event)')
            before = 'int audit=17*3;System.out.println(audit);'
            setter_noise = 'int independent=9+1;System.out.println(independent);'
        else:
            text = text.replace('request() {', 'request(event: number) {')
            text = text.replace('act(): void;', 'act(event: number): void;')
            text = text.replace('act() {', 'act(event: number) {')
            before = 'const audit=17*3;console.log(audit);'
            setter_noise = 'const independent=9+1;console.log(independent);'
        text = text.replace('this.state.act()', 'this.state.act(event)')
        replacement = (before if noise else '') + 'if(event>0){this.ctx.install(new Ready());}'
        if mutation == 'different-current-context':
            replacement = 'this.ctx=new Context(null);' + replacement
        text = text.replace('this.ctx.install(new Ready());', replacement)
        if noise:
            text = text.replace('this.state = candidate;', setter_noise + 'this.state = candidate;')
        if mutation == 'wrong-event':
            text = text.replace('this.state.act(event)', 'this.state.act(0)')
        if mutation == 'wrong-transition-slot':
            text = text.replace('this.state = candidate', 'this.other = candidate')
        if mutation == 'current-state-replaced':
            text = text.replace('this.state.act(event)', 'this.state=new Ready();this.state.act(event)')
    return text


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noise', [False, True])
def test_event_transition_tolerates_local_work_in_action_and_setter(language, noise):
    assert detect(source(language, noise=noise), language)[1]['matches']


@pytest.mark.parametrize('language', LANGUAGES)
def test_noise_cannot_hide_transition_writing_another_slot(language):
    assert not detect(source(language, 'wrong-transition-slot'), language)[1]['matches']


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['wrong-event', 'different-current-context', 'current-state-replaced'])
@pytest.mark.xfail(strict=True, reason='Stronger event/current-owner/current-dispatch contract needs temporal data flow, not historical constructor/slot associations; algorithms/state.md')
def test_desired_event_transition_preserves_event_owner_and_active_state(language, mutation):
    assert not detect(source(language, mutation), language)[1]['matches']
