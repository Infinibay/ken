import pytest

def test_explicit_syntax_graph_retains_context_failure_and_runs_independent_chain():
    from tools.rust_migration.symbol_profile_sequence import run_profiles,DEPENDENCIES
    graph=DEPENDENCIES|dict(syntax=('preferences',));calls=[]
    def fail():calls.append('context');raise ValueError('mismatch')
    callbacks={name:(lambda n=name:calls.append(n))for name in graph};callbacks['context']=fail
    states=run_profiles(callbacks,dependencies=graph)
    assert calls==list(graph)and states['context']['state']=='failed'
    assert all(states[name]['state']=='passed'for name in graph if name!='context')

def test_syntax_is_skipped_when_its_actual_preference_parent_fails():
    from tools.rust_migration.symbol_profile_sequence import run_profiles,DEPENDENCIES
    graph=DEPENDENCIES|dict(syntax=('preferences',));calls=[]
    def fail():calls.append('preferences');raise ValueError('mismatch')
    callbacks={name:(lambda n=name:calls.append(n))for name in graph};callbacks['preferences']=fail
    states=run_profiles(callbacks,dependencies=graph)
    assert calls==list(DEPENDENCIES)
    assert states['syntax']==dict(state='skipped',dependencies=['preferences'])

@pytest.mark.parametrize('graph',[{'a':('missing',)},{'a':('b',),'b':('a',)},{'a':('b',),'b':()}])
def test_invalid_dependency_graph_rejects_before_any_callback(graph):
    from tools.rust_migration.symbol_profile_sequence import run_profiles
    calls=[]
    with pytest.raises(ValueError):run_profiles({name:lambda:calls.append('called')for name in graph},dependencies=graph)
    assert not calls
