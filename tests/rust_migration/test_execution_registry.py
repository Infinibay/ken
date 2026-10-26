from pathlib import Path
import copy,json,shutil,os
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_exact_descriptor_and_authenticated_reference_required(tmp_path):
    from tools.rust_migration.execution_registry import select,INDEX
    from tools.rust_migration.execution_profiles import fingerprint
    from tools.rust_migration.native_json import identity
    path=tmp_path/'reference.json';path.write_text('{"cases":[]}')
    descriptor=dict(target='linux-x86_64',core='observed',threads=1)
    row=dict(id=fingerprint(descriptor),descriptor=descriptor,reference=dict(path='reference.json',encoding='json',**identity(path)))
    index=tmp_path/INDEX;index.parent.mkdir(parents=True);index.write_text(json.dumps(dict(format='ken-execution-reference-registry/1',families=dict(alignment=[row]))))
    assert select(tmp_path,'alignment',descriptor)==(row,dict(cases=[]))
    with pytest.raises(ValueError):select(tmp_path,'alignment',descriptor|dict(core='unknown'))
    path.write_text('{}')
    with pytest.raises(ValueError):select(tmp_path,'alignment',descriptor)


def test_ambiguous_and_unsafe_registry_entries_reject(tmp_path):
    from tools.rust_migration.execution_registry import select,INDEX
    from tools.rust_migration.execution_profiles import fingerprint
    descriptor=dict(target='linux-x86_64')
    row=dict(id=fingerprint(descriptor),descriptor=descriptor,reference=dict(path='../outside',encoding='json',bytes=1,sha256='0'*64))
    path=tmp_path/INDEX;path.parent.mkdir(parents=True);value=dict(format='ken-execution-reference-registry/1',families=dict(context=[row,row]));path.write_text(json.dumps(value))
    with pytest.raises(ValueError):select(tmp_path,'context',descriptor)
    value['families']['context'].pop();path.write_text(json.dumps(value))
    with pytest.raises(ValueError):select(tmp_path,'context',descriptor)
