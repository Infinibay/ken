"""Explicit native fastembed input reaches all composed validation boundaries."""
import os
from pathlib import Path
import sys

import pytest

from tools.rust_migration.preparation import (
    PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation,
    PreparedTranslationBuild, PreparedNativeFastEmbed, fastembed_environment,
)
from tools.rust_migration.reference import Reference, reference_env
from tools.rust_migration.validate import _validation_environment


def test_fastembed_requires_explicit_absolute_input_and_does_not_leak_to_original(tmp_path,monkeypatch):
    from tools.rust_migration.preparation import FASTEMBED_ENV
    for key in FASTEMBED_ENV:monkeypatch.delenv(key,raising=False)
    assert fastembed_environment()=={}
    for invalid in ['','relative']:
        monkeypatch.setenv('KEN_FASTEMBED_PROBE',invalid)
        with pytest.raises(ValueError):fastembed_environment()
    monkeypatch.setenv('KEN_FASTEMBED_PROBE','relative')
    explicit=tmp_path/'probe'
    before=dict(os.environ)
    assert fastembed_environment(PreparedNativeFastEmbed(explicit,tmp_path/'sources',tmp_path/'registry'))=={'KEN_FASTEMBED_PROBE':str(explicit),'KEN_FASTEMBED_SOURCES':str(tmp_path/'sources'),'KEN_FASTEMBED_REGISTRY':str(tmp_path/'registry')}
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    env=_validation_environment(reference,tmp_path,tmp_path/'out',tmp_path/'native',fastembed=PreparedNativeFastEmbed(explicit,tmp_path/'sources',tmp_path/'registry'))
    assert env['KEN_FASTEMBED_PROBE']==str(explicit)
    assert all(env[key]==value for key,value in PreparedNativeFastEmbed(explicit,tmp_path/'sources',tmp_path/'registry').environment().items())
    assert not any(key.startswith('KEN_FASTEMBED_') for key in reference_env(reference,tmp_path/'oracle'))
    assert dict(os.environ)==before
    with pytest.raises(ValueError):fastembed_environment(PreparedNativeFastEmbed(Path('relative'),tmp_path/'sources',tmp_path/'registry'))


@pytest.mark.parametrize('key',['KEN_FASTEMBED_PROBE','KEN_FASTEMBED_SOURCES','KEN_FASTEMBED_REGISTRY'])
def test_fastembed_partial_or_relative_inherited_input_rejects(key,tmp_path,monkeypatch):
    from tools.rust_migration.preparation import FASTEMBED_ENV
    for name in FASTEMBED_ENV:monkeypatch.delenv(name,raising=False)
    monkeypatch.setenv(key,str(tmp_path/'one'))
    with pytest.raises(ValueError):fastembed_environment()
    for name in FASTEMBED_ENV:monkeypatch.setenv(name,str(tmp_path/name))
    assert set(fastembed_environment())==set(FASTEMBED_ENV)
    monkeypatch.setenv(key,'relative')
    with pytest.raises(ValueError):fastembed_environment()


class BoundaryReached(Exception):pass


@pytest.mark.parametrize('profile',['storage','policy','translation','ettin','context','table','model','base'])
def test_every_prior_profile_forwards_explicit_fastembed(profile,tmp_path,monkeypatch):
    from tools.rust_migration import translation_validate as tr,ettin_validate as ev,context_validate as cv
    from tools.rust_migration import table_validate as tv,model_validate as mv,validate as bv
    probe=PreparedNativeFastEmbed(tmp_path/'fastembed-probe',tmp_path/'sources',tmp_path/'registry');seen={}
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'library',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    translation=PreparedNativeTranslation(tmp_path/'translation',tmp_path/'translation-probe',PreparedTranslationBuild(tmp_path/'cmake'))
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    common=[tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',tmp_path/'table.npz']
    ending=[tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest']
    def lower(*args,**kwargs):seen.update(kwargs);raise BoundaryReached()
    def command(repo,env,*args):seen.update(env);raise BoundaryReached()
    if profile=='storage':
        from tools.rust_migration import storage_validate as sv
        from tools.rust_migration.preparation import PreparedNativeStorage
        storage_path=tmp_path/'storage-probe';storage_path.touch();storage_path.chmod(0o755)
        driver=storage_path.with_name('storage_recovery_driver');driver.touch();driver.chmod(0o755)
        monkeypatch.setattr(sv,'storage_fingerprints',lambda *a:{})
        monkeypatch.setattr(sv,'validate_policy',lower)
        with pytest.raises(BoundaryReached):sv.validate_storage(*common,context,ettin,translation,tmp_path/'policy',PreparedNativeStorage(storage_path),*ending,fastembed=probe)
    elif profile=='policy':
        from tools.rust_migration import policy_validate as pv
        policy=tmp_path/'policy';policy.touch();policy.chmod(0o755)
        monkeypatch.setattr(pv,'policy_fingerprints',lambda *a:{})
        monkeypatch.setattr(pv,'validate_translation',lower)
        with pytest.raises(BoundaryReached):pv.validate_policy(*common,context,ettin,translation,policy,*ending,fastembed=probe)
    elif profile=='translation':
        monkeypatch.setattr(tr,'translation_fingerprints',lambda *a:{})
        monkeypatch.setattr(tr,'inspect_prerequisites',lambda *a:{})
        monkeypatch.setattr(tr,'validate_ettin',lower)
        with pytest.raises(BoundaryReached):tr.validate_translation(*common,context,ettin,translation,*ending,fastembed=probe)
    elif profile=='ettin':
        monkeypatch.setattr(ev,'ettin_fingerprints',lambda *a:{})
        monkeypatch.setattr(ev,'validate_context',lower)
        with pytest.raises(BoundaryReached):ev.validate_ettin(*common,context,ettin,*ending,fastembed=probe)
    elif profile=='context':
        monkeypatch.setattr(cv,'context_fingerprints',lambda *a:{})
        monkeypatch.setattr(cv,'validate_tables',lower)
        with pytest.raises(BoundaryReached):cv.validate_context(*common,context,*ending,fastembed=probe)
    elif profile=='table':
        monkeypatch.setattr(tv,'table_fingerprints',lambda *a:{})
        monkeypatch.setattr(tv,'validate_models',lower)
        with pytest.raises(BoundaryReached):tv.validate_tables(*common,*ending,fastembed=probe)
    elif profile=='model':
        monkeypatch.setattr(mv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(mv,'_model_fingerprints',lambda *a:{})
        monkeypatch.setattr(mv,'_command',command)
        with pytest.raises(BoundaryReached):mv.validate_models(tmp_path,reference,tmp_path/'probe',tmp_path/'potion',*ending,fastembed=probe)
    else:
        monkeypatch.setattr(bv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(bv,'_fingerprints',lambda *a:{})
        monkeypatch.setattr(bv,'_command',command)
        with pytest.raises(BoundaryReached):bv.run(tmp_path,reference,tmp_path/'native',tmp_path/'out',fastembed=probe)
    if profile in ['base','model']:
        assert all(seen[key]==value for key,value in probe.environment().items())
    else:assert seen['fastembed']==probe
