"""Prepared Ettin inputs reach native validators and stay out of the oracle."""
import os
from pathlib import Path
import sys

import pytest

from tools.rust_migration.preparation import PreparedNativeContext, PreparedNativeEttin, ettin_environment
from tools.rust_migration.reference import Reference, reference_env
from tools.rust_migration.validate import _validation_environment


def test_ettin_inputs_are_explicit_typed_and_do_not_mutate_or_leak_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('KEN_ETTIN_SOURCE','relative-ambient-source')
    monkeypatch.setenv('KEN_ETTIN_PROBE','relative-ambient-probe')
    monkeypatch.setenv('KEN_ETTIN_SECRET','do-not-forward')
    prepared=PreparedNativeEttin(tmp_path/'source',tmp_path/'probe')
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'core',tmp_path/'context-probe')
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    before=dict(os.environ)
    env=_validation_environment(reference,tmp_path,tmp_path/'out',tmp_path/'native',context=context,ettin=prepared)
    assert env['KEN_ETTIN_SOURCE']==str(prepared.source)
    assert env['KEN_ETTIN_PROBE']==str(prepared.probe)
    assert 'KEN_ETTIN_SECRET' not in env
    assert env['KEN_ORT_LIBRARY']==str(context.library)
    isolated=reference_env(reference,tmp_path/'original-env')
    assert {key for key in isolated if key.startswith('KEN_')}=={'KEN_CONFIG_DIR','KEN_CACHE_DIR'}
    assert isolated['KEN_CONFIG_DIR']==str(tmp_path/'original-env/config')
    assert isolated['KEN_CACHE_DIR']==str(tmp_path/'original-env/cache')
    assert dict(os.environ)==before


def test_ettin_environment_has_no_invented_defaults_and_rejects_relative_paths(tmp_path,monkeypatch):
    for name in ['KEN_ETTIN_SOURCE','KEN_ETTIN_PROBE']:monkeypatch.delenv(name,raising=False)
    assert ettin_environment()=={}
    monkeypatch.setenv('KEN_ETTIN_SOURCE',str(tmp_path/'source'))
    assert ettin_environment()=={'KEN_ETTIN_SOURCE':str(tmp_path/'source')}
    monkeypatch.setenv('KEN_ETTIN_PROBE','relative')
    with pytest.raises(ValueError):ettin_environment()
    for item in [PreparedNativeEttin(Path('relative'),tmp_path/'probe'),
                 PreparedNativeEttin(tmp_path/'source',Path('relative'))]:
        with pytest.raises(ValueError):item.environment()


class BoundaryReached(Exception):pass


@pytest.mark.parametrize('profile',['context','table','model'])
def test_every_profile_forwards_explicit_ettin_inputs_to_its_native_boundary(profile,tmp_path,monkeypatch):
    from tools.rust_migration import context_validate as cv,table_validate as tv,model_validate as mv
    prepared=PreparedNativeEttin(tmp_path/'source',tmp_path/'probe')
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'core',tmp_path/'context-probe')
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    seen={}
    def lower(*args,**kwargs):
        seen.update(kwargs);raise BoundaryReached()
    if profile=='context':
        monkeypatch.setattr(cv,'context_fingerprints',lambda *a:{})
        monkeypatch.setattr(cv,'validate_tables',lower)
        with pytest.raises(BoundaryReached):
            cv.validate_context(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
                tmp_path/'table.npz',context,tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest',ettin=prepared)
        assert seen['ettin'] is prepared and seen['context'] is context
    elif profile=='table':
        monkeypatch.setattr(tv,'table_fingerprints',lambda *a:{})
        monkeypatch.setattr(tv,'validate_models',lower)
        with pytest.raises(BoundaryReached):
            tv.validate_tables(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
                tmp_path/'table.npz',tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest',context=context,ettin=prepared)
        assert seen['ettin'] is prepared and seen['context'] is context
    else:
        monkeypatch.setattr(mv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(mv,'_model_fingerprints',lambda *a:{})
        def command(repo,env,*args):
            seen.update(env);raise BoundaryReached()
        monkeypatch.setattr(mv,'_command',command)
        with pytest.raises(BoundaryReached):
            mv.validate_models(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'out',
                tmp_path/'baseline',tmp_path/'manifest',context=context,ettin=prepared)
        assert seen['KEN_ETTIN_SOURCE']==str(prepared.source)
        assert seen['KEN_ETTIN_PROBE']==str(prepared.probe)
