"""Observer ``language-event``: a C# event with registration, removal and raising.

The variant is a published rule, so the test goes through the registry name
``observer#language-event`` rather than a private copy of the query.

Two exclusions are asserted, not just documented: a plain delegate field is not
an event, and a custom accessor event (whose semantics are unknown) is not
marked either.
"""
import pytest

from ken.structural.catalog import _load_catalog
from ken.structural.frontend import lower_source
from ken.structural.rules import builtin_rules, execute_rules, named_rule
from ken.structural.semantic import link_project

RULE = 'observer#language-event'

POSITIVE = '''using System;
public class Publisher {
    public event Action<int>? Changed;
    public void Attach(Action<int> first, Action<int> second) {
        Changed += first;
        Changed += second;
    }
    public void Detach(Action<int> handler) { Changed -= handler; }
    public void Raise(int payload) { Changed?.Invoke(payload); }
}
'''

PLAIN_DELEGATE = '''using System;
public class Publisher {
    public Action<int>? Plain;
    public void Attach(Action<int> handler) { Plain += handler; }
    public void Detach(Action<int> handler) { Plain -= handler; }
    public void Raise(int payload) { Plain?.Invoke(payload); }
}
'''

CUSTOM_ACCESSOR = '''using System;
public class Publisher {
    public event Action<int>? Custom {
        add { }
        remove { }
    }
    public void Attach(Action<int> handler) { Custom += handler; }
    public void Detach(Action<int> handler) { Custom -= handler; }
    public void Raise(int payload) { Custom?.Invoke(payload); }
}
'''

NEVER_RAISED = '''using System;
public class Publisher {
    public event Action<int>? Changed;
    public void Attach(Action<int> handler) { Changed += handler; }
    public void Detach(Action<int> handler) { Changed -= handler; }
}
'''

TWO_EVENTS = '''using System;
public class Publisher {
    public event Action<int>? First;
    public event Action<int>? Second;
    public void Attach(Action<int> handler) { First += handler; }
    public void Detach(Action<int> handler) { Second -= handler; }
    public void Raise(int payload) { Second?.Invoke(payload); }
}
'''

CROSS_CLASS = '''using System;
public class Publisher {
    public event Action<int>? Changed;
    public void Raise(int payload) { Changed?.Invoke(payload); }
}
public class Subscriber {
    private Publisher publisher = new Publisher();
    public void Subscribe(Action<int> handler) { publisher.Changed += handler; }
    public void Unsubscribe(Action<int> handler) { publisher.Changed -= handler; }
}
'''


def graph_for(source):
    graph = link_project([lower_source(source, 'csharp', 'events.cs')])
    assert not graph.diagnostics, graph.diagnostics
    return graph


def detect(source):
    registry = builtin_rules()
    result = execute_rules(graph_for(source), [named_rule(RULE, registry)], registry=registry)
    assert result['complete'], result['outcomes']
    return result['matches']


def test_declared_event_with_registration_removal_and_raise_is_detected():
    matches = detect(POSITIVE)
    assert len(matches) == 1
    bindings = matches[0]['bindings']
    assert bindings['$unit'].endswith('/CLASS:Publisher')
    assert bindings['$event'].endswith('/STORAGE:Changed')
    assert bindings['$attach'].endswith('/CALLABLE:Attach@82')
    assert bindings['$detach'].endswith('/CALLABLE:Detach@205')
    assert bindings['$raise'].endswith('/CALLABLE:Raise@273')


def test_both_handlers_are_recorded_with_their_parameter():
    """The scenario registers two handlers and removes one of them."""
    graph = graph_for(POSITIVE)
    additions = [f for f in graph.facts if f.relation == 'ADDS_HANDLER']
    removals = [f for f in graph.facts if f.relation == 'REMOVES_HANDLER']
    assert len(additions) == 2
    assert len(removals) == 1
    assert {f.attrs['handler'].rsplit('/', 1)[-1] for f in additions} == {'PARAMETER:first@101',
                                                                         'PARAMETER:second@120'}


def test_registration_from_another_class_resolves_to_the_declared_event():
    """The same storage, reached through a member access on a typed receiver."""
    graph = graph_for(CROSS_CLASS)
    additions = [f for f in graph.facts if f.relation == 'ADDS_HANDLER']
    assert len(additions) == 1
    assert additions[0].object.endswith('/STORAGE:Changed')
    assert '/CALLABLE:Subscribe@' in additions[0].subject
    member = [f for f in graph.facts if f.relation == 'MEMBER_DECLARATION']
    assert len(member) == 1
    assert member[0].object.endswith('/STORAGE:Changed')


def test_plain_delegate_field_is_not_an_event():
    """``+=`` on a delegate-typed field is not a handler registration."""
    graph = graph_for(PLAIN_DELEGATE)
    assert not [f for f in graph.facts if f.relation == 'DECLARES_EVENT']
    assert not [f for f in graph.facts if f.relation == 'ADDS_HANDLER']
    assert not detect(PLAIN_DELEGATE)


def test_custom_accessor_event_is_left_unknown():
    """Add/remove semantics of a custom accessor are not guessed."""
    graph = graph_for(CUSTOM_ACCESSOR)
    assert not [f for f in graph.facts if f.relation == 'DECLARES_EVENT']
    assert not [f for f in graph.facts if f.relation == 'ADDS_HANDLER']
    assert not detect(CUSTOM_ACCESSOR)


def test_event_never_raised_is_rejected():
    assert not detect(NEVER_RAISED)


def test_registration_and_removal_on_different_events_are_rejected():
    assert not detect(TWO_EVENTS)


def test_variant_is_ready_for_its_single_declared_language():
    rule = next(r for r in _load_catalog() if r.id == 'observer')
    row = next(v for v in rule.variants if v['id'] == 'language-event')
    assert row['languages'] == ['csharp']
    assert row['status'] == 'ready'
    assert isinstance(row.get('query'), str) and row['query'].strip()
    assert 'DECLARES_EVENT' in row['query'] and 'RAISES_EVENT' in row['query']
