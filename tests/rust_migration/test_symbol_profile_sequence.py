from collections import OrderedDict

def test_context_failure_preserves_failure_and_runs_independent_symbol_profiles():
    from tools.rust_migration.symbol_profile_sequence import run_profiles
    calls=[]
    def fail():
        calls.append('context');raise RuntimeError('context mismatch')
    states=run_profiles(OrderedDict(context=fail,ettin=lambda:calls.append('ettin'),views=lambda:calls.append('views'),preferences=lambda:calls.append('preferences')))
    assert calls==['context','ettin','views','preferences']
    assert states['context']==dict(state='failed',error='RuntimeError: context mismatch')
    assert all(states[n]['state']=='passed'for n in('ettin','views','preferences'))
    assert any(row['state']!='passed'for row in states.values())

def test_ettin_failure_skips_only_dependent_views_and_preferences():
    from tools.rust_migration.symbol_profile_sequence import run_profiles
    calls=[]
    def fail():
        calls.append('ettin');raise ValueError('ettin mismatch')
    states=run_profiles(OrderedDict(context=lambda:calls.append('context'),ettin=fail,views=lambda:calls.append('views'),preferences=lambda:calls.append('preferences')))
    assert calls==['context','ettin'] and states['ettin']['state']=='failed'
    assert states['views']==dict(state='skipped',dependencies=['ettin'])
    assert states['preferences']==dict(state='skipped',dependencies=['views'])

def test_all_profiles_must_complete_for_global_success():
    from tools.rust_migration.symbol_profile_sequence import run_profiles
    states=run_profiles(OrderedDict((name,lambda:None)for name in('context','ettin','views','preferences')))
    assert all(row==dict(state='passed')for row in states.values())
