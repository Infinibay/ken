"""Explicit native storage input reaches all composed validation boundaries."""
import os
from pathlib import Path
import sys

import pytest

from tools.rust_migration.preparation import (
    PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation,
    PreparedTranslationBuild, PreparedNativeStorage, storage_environment,
)
from tools.rust_migration.reference import Reference, reference_env
from tools.rust_migration.validate import _validation_environment


def test_storage_requires_explicit_absolute_input_and_does_not_leak_to_original(tmp_path,monkeypatch):
    monkeypatch.delenv('KEN_STORAGE_PROBE',raising=False)
    assert storage_environment()=={}
    for invalid in ['','relative']:
        monkeypatch.setenv('KEN_STORAGE_PROBE',invalid)
        with pytest.raises(ValueError):storage_environment()
    monkeypatch.setenv('KEN_STORAGE_PROBE','relative')
    explicit=tmp_path/'probe'
    before=dict(os.environ)
    assert storage_environment(PreparedNativeStorage(explicit))=={'KEN_STORAGE_PROBE':str(explicit)}
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    env=_validation_environment(reference,tmp_path,tmp_path/'out',tmp_path/'native',storage=PreparedNativeStorage(explicit))
    assert env['KEN_STORAGE_PROBE']==str(explicit)
    assert 'KEN_STORAGE_PROBE' not in reference_env(reference,tmp_path/'oracle')
    assert dict(os.environ)==before
    with pytest.raises(ValueError):storage_environment(PreparedNativeStorage(Path('relative')))


class BoundaryReached(Exception):pass


@pytest.mark.parametrize('profile',['policy','translation','ettin','context','table','model','base'])
def test_every_prior_profile_forwards_explicit_storage(profile,tmp_path,monkeypatch):
    from tools.rust_migration import translation_validate as tr,ettin_validate as ev,context_validate as cv
    from tools.rust_migration import table_validate as tv,model_validate as mv,validate as bv
    probe=PreparedNativeStorage(tmp_path/'storage-probe');seen={}
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'library',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    translation=PreparedNativeTranslation(tmp_path/'translation',tmp_path/'translation-probe',PreparedTranslationBuild(tmp_path/'cmake'))
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    common=[tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',tmp_path/'table.npz']
    ending=[tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest']
    def lower(*args,**kwargs):seen.update(kwargs);raise BoundaryReached()
    def command(repo,env,*args):seen.update(env);raise BoundaryReached()
    if profile=='policy':
        from tools.rust_migration import policy_validate as pv
        policy=tmp_path/'policy';policy.touch();policy.chmod(0o755)
        monkeypatch.setattr(pv,'policy_fingerprints',lambda *a:{})
        monkeypatch.setattr(pv,'validate_translation',lower)
        with pytest.raises(BoundaryReached):pv.validate_policy(*common,context,ettin,translation,policy,*ending,storage=probe)
    elif profile=='translation':
        monkeypatch.setattr(tr,'translation_fingerprints',lambda *a:{})
        monkeypatch.setattr(tr,'inspect_prerequisites',lambda *a:{})
        monkeypatch.setattr(tr,'validate_ettin',lower)
        with pytest.raises(BoundaryReached):tr.validate_translation(*common,context,ettin,translation,*ending,storage=probe)
    elif profile=='ettin':
        monkeypatch.setattr(ev,'ettin_fingerprints',lambda *a:{})
        monkeypatch.setattr(ev,'validate_context',lower)
        with pytest.raises(BoundaryReached):ev.validate_ettin(*common,context,ettin,*ending,storage=probe)
    elif profile=='context':
        monkeypatch.setattr(cv,'context_fingerprints',lambda *a:{})
        monkeypatch.setattr(cv,'validate_tables',lower)
        with pytest.raises(BoundaryReached):cv.validate_context(*common,context,*ending,storage=probe)
    elif profile=='table':
        monkeypatch.setattr(tv,'table_fingerprints',lambda *a:{})
        monkeypatch.setattr(tv,'validate_models',lower)
        with pytest.raises(BoundaryReached):tv.validate_tables(*common,*ending,storage=probe)
    elif profile=='model':
        monkeypatch.setattr(mv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(mv,'_model_fingerprints',lambda *a:{})
        monkeypatch.setattr(mv,'_command',command)
        with pytest.raises(BoundaryReached):mv.validate_models(tmp_path,reference,tmp_path/'probe',tmp_path/'potion',*ending,storage=probe)
    else:
        monkeypatch.setattr(bv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(bv,'_fingerprints',lambda *a:{})
        monkeypatch.setattr(bv,'_command',command)
        with pytest.raises(BoundaryReached):bv.run(tmp_path,reference,tmp_path/'native',tmp_path/'out',storage=probe)
    if profile in ['base','model']:assert seen['KEN_STORAGE_PROBE']==str(probe.probe)
    else:assert seen['storage']==probe
