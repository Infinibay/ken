"""Nominal contract lookup is separate from possible concrete dispatch targets."""
import pytest
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.rules import execute_rules, SavedRule

SOURCES = {
 'python': 'class API:\n def act(self): pass\nclass Impl(API):\n def act(self): pass\nclass C:\n target: API\n def __init__(self): self.target=Impl()\n def run(self): self.target.act()\n',
 'typescript': 'interface API { act(): void; } class Impl implements API { act() {} } class C { target:API; constructor(){this.target=new Impl();} run(){this.target.act();} }',
 'java': 'interface API { void act(); } class Impl implements API { public void act(){} } class C { API target; C(){this.target=new Impl();} void run(){this.target.act();} }',
 'csharp': 'interface API { void act(); } class Impl: API { public void act(){} } class C { API target; C(){this.target=new Impl();} void run(){this.target.act();} }',
}


@pytest.mark.parametrize('language', SOURCES)
def test_declared_slot_does_not_erase_concrete_ambiguity(language):
    graph = link_project([lower_source(SOURCES[language], language, 'dispatch')])
    assert not graph.diagnostics
    slots = [f for f in graph.facts if f.relation == 'DECLARED_TARGET']
    assert len(slots) == 1
    f = slots[0]
    assert '/INTERFACE:API/' in f.object or '/CLASS:API/' in f.object
    assert f.attrs['basis'] == 'nominal-annotation'
    assert len([e for e in graph.facts if e.subject == f.subject and e.relation == 'MAY_TARGET']) == 2
    assert not any(e.subject == f.subject and e.relation == 'TARGET' for e in graph.facts)
    out = execute_rules(graph, [SavedRule('declared', 'query q { require $call DECLARED_TARGET $slot; emit $call, $slot; }')])
    assert out['complete'] and out['matches']


@pytest.mark.parametrize('source', [
 'interface API {act():void; act(x:number):void;} class C { target:API; run(){this.target.act();}}',
 'class C { run(target){target.act();}}',
 'class C { target:Missing; run(){this.target.act();}}',
 'interface API {act():void;} class C { target:API; run(){this.target.other();}}',
])
def test_missing_untyped_and_overloaded_slots_not_guessed(source):
    graph = link_project([lower_source(source, 'typescript', 'dispatch.ts')])
    assert not graph.diagnostics
    assert not any(f.relation == 'DECLARED_TARGET' for f in graph.facts)
