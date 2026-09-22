"""Mediator coordination contracts: bidirectional participants and event flow."""
import re

import pytest

from .contract_support import contract_matches

from .test_gof_executable import SOURCES, evaluate


LANGUAGES = ['python', 'java', 'typescript']


def source(language, noisy=False):
    if language == 'python':
        trace = 'print(3);' if noisy else ''
        return ('class First:\n def act(self, data): pass\n'
                f' def changed(self, hub: Hub): {trace}hub.coordinate(1)\n'
                'class Second:\n def act(self, data): pass\n'
                f' def changed(self, hub: Hub): {trace}hub.coordinate(2)\n'
                'class Hub:\n def __init__(self, one: First, two: Second): self.one=one;self.two=two\n'
                ' def coordinate(self, event):\n'
                + ('  metric=2+3\n  print(metric)\n' if noisy else '')
                + '  if event==1:\n   self.one.act(event)\n  else:\n   self.two.act(event)\n')
    if language == 'java':
        trace = 'System.out.println(3);' if noisy else ''
        extra = 'int metric=2+3;System.out.println(metric);' if noisy else ''
        return (f'class First {{void act(int data){{}} void changed(Hub hub){{{trace}hub.coordinate(1);}}}}'
                f'class Second {{void act(int data){{}} void changed(Hub hub){{{trace}hub.coordinate(2);}}}}'
                'class Hub {First one;Second two;Hub(First one,Second two){this.one=one;this.two=two;}'
                'void coordinate(int event){' + extra + 'if(event==1){this.one.act(event);}else{this.two.act(event);}}}')
    trace = 'console.log(3);' if noisy else ''
    extra = 'const metric=2+3;console.log(metric);' if noisy else ''
    return (f'class First {{act(data:number):void{{}}changed(hub:Hub):void{{{trace}hub.coordinate(1);}}}}'
            f'class Second {{act(data:number):void{{}}changed(hub:Hub):void{{{trace}hub.coordinate(2);}}}}'
            'class Hub {one:First;two:Second;constructor(one:First,two:Second){this.one=one;this.two=two;}'
            'coordinate(event:number):void{' + extra + 'if(event==1){this.one.act(event);}else{this.two.act(event);}}}')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('noisy', [False, True])
@pytest.mark.parametrize('renamed', [False, True])
def test_event_coordination_survives_independent_work(language, noisy, renamed):
    text = source(language, noisy)
    if renamed:
        names = {'First': 'Editor', 'Second': 'Preview', 'Hub': 'Coordinator',
                 'coordinate': 'route', 'changed': 'signal', 'act': 'apply', 'event': 'tag'}
        text = re.sub(r'\b\w+\b', lambda m: names.get(m[0], m[0]), text)
    assert evaluate(text, language, 'mediator')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('mutation', ['missing-upstream', 'missing-downstream', 'other-downstream'])
def test_missing_bidirectional_participation_is_rejected(language, mutation):
    text = source(language, noisy=True)
    if mutation == 'missing-upstream':
        text = text.replace('hub.coordinate(2)', 'pass') if language == 'python' else text.replace('hub.coordinate(2);', '')
    elif mutation == 'missing-downstream':
        text = text.replace('self.two.act(event)', 'pass').replace('this.two.act(event);', '')
    else:
        text = text.replace('self.two.act(event)', 'self.other.act(event)').replace('this.two.act(event)', 'this.other.act(event)')
    assert not evaluate(text, language, 'mediator')


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('collaboration', ['observer', 'facade'])
def test_broadcast_or_facade_without_coordination_loop_is_not_mediator(language, collaboration):
    # Structural contrasts, not a declaration that these patterns are exclusive.
    assert not evaluate(SOURCES[language][collaboration], language, 'mediator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_two_instances_of_one_colleague_type_can_be_mediated(language):
    text = source(language).replace('Second', 'First')
    # Remove duplicate class definition after unifying the type, retain both fields.
    first = text.index('class First')
    second = text.index('class First', first + 1)
    hub = text.index('class Hub', second)
    text = text[:second] + text[hub:]
    text = text.replace('changed(self, hub: Hub)', 'changed(self, hub: Hub, mode)')
    text = text.replace('changed(Hub hub)', 'changed(Hub hub,int mode)').replace('changed(hub:Hub)', 'changed(hub:Hub,mode:number)')
    text = text.replace('hub.coordinate(1)', 'hub.coordinate(mode)')
    assert evaluate(text, language, 'mediator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_unreachable_coordination_is_not_an_executed_algorithm(language):
    text = source(language)
    if language == 'python':
        text = text.replace(' def coordinate(self, event):\n', ' def coordinate(self, event):\n  return\n')
    elif language == 'java':
        text = text.replace('void coordinate(int event){', 'void coordinate(int event){return;')
    else:
        text = text.replace('coordinate(event:number):void{', 'coordinate(event:number):void{return;')
    assert not evaluate(text, language, 'mediator')


@pytest.mark.parametrize('language', LANGUAGES)
def test_payload_contract_rejects_discarded_event_data(language):
    text = source(language).replace('act(event)', 'act(0)')
    assert contract_matches(source(language), language, 'mediator.event_delivery')
    assert not contract_matches(text, language, 'mediator.event_delivery')
