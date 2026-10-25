"""A native SDK publisher must reject foreign or corrupted inputs without writes."""
from pathlib import Path
import json,struct
import pytest
ROOT=Path(__file__).resolve().parents[2]

def test_existing_sdk_is_never_overwritten_or_used_as_another_target(tmp_path):
    from tools.rust_migration.native_core_prepare import prepare_native_cores
    out=tmp_path/'sdk';out.mkdir();sentinel=out/'foreign';sentinel.write_bytes(b'keep')
    with pytest.raises(ValueError,match='destination'):
        prepare_native_cores(ROOT,tmp_path/'cache',out,target=('linux','x86_64'))
    assert sentinel.read_bytes()==b'keep'and set(p.name for p in out.iterdir())=={'foreign'}
    assert not(tmp_path/'cache').exists()

def test_foreign_sdk_preparation_rejects_before_cache_or_output(tmp_path,monkeypatch):
    from tools.rust_migration import native_core_prepare as module
    monkeypatch.setattr(module.platform,'system',lambda:'Linux');monkeypatch.setattr(module.platform,'machine',lambda:'x86_64')
    with pytest.raises(ValueError,match='host'):
        module.prepare_native_cores(ROOT,tmp_path/'cache',tmp_path/'sdk',target=('linux','aarch64'))
    assert not(tmp_path/'cache').exists()and not(tmp_path/'sdk').exists()

def test_changed_cached_wheel_is_preserved_and_never_published(tmp_path,monkeypatch):
    from tools.rust_migration import native_core_prepare as module
    monkeypatch.setattr(module.platform,'system',lambda:'Linux');monkeypatch.setattr(module.platform,'machine',lambda:'x86_64')
    records=json.loads((ROOT/'tools/rust_migration/data/native-sdk-sources.json').read_bytes())['sources']
    source=next(r for r in records if(r['package'],r['os'],r['arch'])==('onnxruntime','linux','x86_64'))
    cache=tmp_path/'cache';cache.mkdir();bad=cache/source['wheel']['filename'];bad.write_bytes(b'corrupted cached source')
    with pytest.raises(ValueError,match='source'):
        module.prepare_native_cores(ROOT,cache,tmp_path/'sdk',target=('linux','x86_64'))
    assert bad.read_bytes()==b'corrupted cached source'and not(tmp_path/'sdk').exists()

def elf(machine):
    value=bytearray(32);value[:6]=b'\x7fELF\x02\x01';value[18:20]=struct.pack('<H',machine);return bytes(value)

@pytest.mark.parametrize('target,machine',[(('linux','x86_64'),62),(('linux','aarch64'),183)])
def test_native_binary_requires_the_declared_64bit_architecture(tmp_path,target,machine):
    from tools.rust_migration.native_binary import check_native_architecture
    path=tmp_path/'library';path.write_bytes(elf(machine));check_native_architecture(path,target)
    for bad in (elf(183 if machine==62 else 62),b'#!/bin/sh\n',b'\x7fELF\x01\x01'+b'\0'*26):
        path.write_bytes(bad)
        with pytest.raises(ValueError):check_native_architecture(path,target)

def test_native_macos_binary_requires_actual_arm64_not_the_platform_label(tmp_path):
    from tools.rust_migration.native_binary import check_native_architecture
    path=tmp_path/'library';header=bytearray(32);header[:4]=b'\xcf\xfa\xed\xfe';header[4:8]=struct.pack('<I',0x0100000c)
    path.write_bytes(header);check_native_architecture(path,('macos','aarch64'))
    header[4:8]=struct.pack('<I',0x01000007);path.write_bytes(header)
    with pytest.raises(ValueError):check_native_architecture(path,('macos','aarch64'))
