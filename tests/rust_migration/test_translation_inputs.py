"""Explicit translation and native build inputs reach every composed validator."""
import os
from pathlib import Path
import sys

import pytest

from tools.rust_migration.preparation import PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation, PreparedTranslationBuild, translation_environment
from tools.rust_migration.reference import Reference, reference_env
from tools.rust_migration.validate import _validation_environment


def test_translation_inputs_override_ambient_values_without_mutating_or_leaking_native_keys(tmp_path,monkeypatch):
    for key in ['KEN_TRANSLATION_SOURCE','KEN_TRANSLATION_PROBE','CMAKE','PKG_CONFIG_PATH','DEP_OPENBLAS_INCLUDE','DEP_OPENBLAS_LIBRARY']:
        monkeypatch.setenv(key,'relative-ambient')
    monkeypatch.setenv('KEN_TRANSLATION_SECRET','secret')
    build=PreparedTranslationBuild(tmp_path/'cmake',tmp_path/'openblas')
    prepared=PreparedNativeTranslation(tmp_path/'source',tmp_path/'probe',build)
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'core',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    before=dict(os.environ)
    env=_validation_environment(reference,tmp_path,tmp_path/'out',tmp_path/'native',context=context,ettin=ettin,translation=prepared)
    assert env['KEN_TRANSLATION_SOURCE']==str(prepared.source)
    assert env['KEN_TRANSLATION_PROBE']==str(prepared.probe)
    assert env['CMAKE']==str(build.cmake)
    assert env['PKG_CONFIG_PATH']==str(build.openblas_prefix/'lib/pkgconfig')
    assert env['DEP_OPENBLAS_INCLUDE']==str(build.openblas_prefix/'include')
    assert env['DEP_OPENBLAS_LIBRARY']==str(build.openblas_prefix/'lib')
    assert 'KEN_TRANSLATION_SECRET' not in env
    assert {key for key in reference_env(reference,tmp_path/'oracle') if key.startswith('KEN_')}=={'KEN_CONFIG_DIR','KEN_CACHE_DIR'}
    assert dict(os.environ)==before


def test_translation_inputs_have_no_invented_defaults_and_reject_relative_paths(tmp_path,monkeypatch):
    keys=['KEN_TRANSLATION_SOURCE','KEN_TRANSLATION_PROBE','CMAKE','PKG_CONFIG_PATH','DEP_OPENBLAS_INCLUDE','DEP_OPENBLAS_LIBRARY']
    for key in keys:monkeypatch.delenv(key,raising=False)
    assert translation_environment()=={}
    for key in keys:
        monkeypatch.setenv(key,'relative')
        with pytest.raises(ValueError):translation_environment()
        monkeypatch.delenv(key)
    for prepared in [PreparedNativeTranslation(Path('relative'),tmp_path/'probe'),
                     PreparedNativeTranslation(tmp_path/'source',Path('relative')),
                     PreparedNativeTranslation(tmp_path/'source',tmp_path/'probe',PreparedTranslationBuild(Path('relative'))),
                     PreparedNativeTranslation(tmp_path/'source',tmp_path/'probe',PreparedTranslationBuild(tmp_path/'cmake',Path('relative')))]:
        with pytest.raises(ValueError):prepared.environment()


class BoundaryReached(Exception):pass


@pytest.mark.parametrize('profile',['ettin','context','table','model'])
def test_each_profile_forwards_typed_translation_and_native_build_inputs(profile,tmp_path,monkeypatch):
    from tools.rust_migration import ettin_validate as ev,context_validate as cv,table_validate as tv,model_validate as mv
    prepared=PreparedNativeTranslation(tmp_path/'source',tmp_path/'probe',PreparedTranslationBuild(tmp_path/'cmake',tmp_path/'openblas'))
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'core',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe')
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable));seen={}
    def lower(*args,**kwargs):seen.update(kwargs);raise BoundaryReached()
    if profile=='ettin':
        monkeypatch.setattr(ev,'ettin_fingerprints',lambda *a:{})
        monkeypatch.setattr(ev,'validate_context',lower)
        with pytest.raises(BoundaryReached):
            ev.validate_ettin(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
                tmp_path/'table.npz',context,ettin,tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest',translation=prepared)
    elif profile=='context':
        monkeypatch.setattr(cv,'context_fingerprints',lambda *a:{})
        monkeypatch.setattr(cv,'validate_tables',lower)
        with pytest.raises(BoundaryReached):
            cv.validate_context(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
                tmp_path/'table.npz',context,tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest',translation=prepared)
    elif profile=='table':
        monkeypatch.setattr(tv,'table_fingerprints',lambda *a:{})
        monkeypatch.setattr(tv,'validate_models',lower)
        with pytest.raises(BoundaryReached):
            tv.validate_tables(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'table-probe',
                tmp_path/'table.npz',tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest',translation=prepared)
    else:
        monkeypatch.setattr(mv,'_verify',lambda *a:{'passed':True})
        monkeypatch.setattr(mv,'_model_fingerprints',lambda *a:{})
        def command(repo,env,*args):seen.update(env);raise BoundaryReached()
        monkeypatch.setattr(mv,'_command',command)
        with pytest.raises(BoundaryReached):
            mv.validate_models(tmp_path,reference,tmp_path/'model-probe',tmp_path/'potion',tmp_path/'out',
                tmp_path/'baseline',tmp_path/'manifest',translation=prepared)
        assert all(seen[k]==v for k,v in prepared.environment().items())
        return
    assert seen['translation'] is prepared


def test_native_source_fingerprint_binds_embedded_unicode_and_registered_fixture_bytes(tmp_path):
    from tools.rust_migration.validate import _fingerprints
    for name in ['Cargo.toml','Cargo.lock','rust-toolchain.toml']:(tmp_path/name).write_text('fixed')
    cases=tmp_path/'cases.json';cases.write_text('[]')
    paths=[tmp_path/'crates/ken-models/src/data/python-unicode15.json',
           tmp_path/'crates/ken-models/tests/fixtures/translation/tiny/model.bin']
    for path in paths:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'original input')
    for path in paths:
        before=_fingerprints(tmp_path,None,cases)
        path.write_bytes(b'changed input')
        assert _fingerprints(tmp_path,None,cases)['native_source']!=before['native_source']
        path.write_bytes(b'original input')
