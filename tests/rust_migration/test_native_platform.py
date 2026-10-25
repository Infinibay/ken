"""Native resource selection must distinguish Linux architectures."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[2]

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def test_registered_cpu_cores_pin_x86_and_preserve_every_arm_record():
    onnx=json.loads((ROOT/'crates/ken-models/resources/onnx-runtime-libraries.json').read_bytes())
    assert onnx['format']=='ken-native-onnx/1'
    records={(r['os'],r['arch']):r for r in onnx['libraries']}
    assert len(records)==len(onnx['libraries'])==3
    assert digest(records['macos','aarch64'])=='06942ff6db3506eca4ff9c05daac61f44bb227fab80401f5e73777690049aa64'
    assert digest(records['linux','aarch64'])=='c1269f45f66f21881a400b76b283724a51990dcdb3a1b928c5c92ad767d51057'
    assert records['linux','x86_64']==dict(os='linux',arch='x86_64',version='1.25.1',api=25,bytes=22769624,sha256='c450a686085f441803ef914fc7e68bd417452e34ba5573344dc3dd40c0c71896')
    torch=json.loads((ROOT/'tools/rust_migration/data/transformer-cores.json').read_bytes())
    cores={(r['os'],r['arch'],r['backend']):r for r in torch['cores']}
    assert len(cores)==len(torch['cores'])==4
    for key,sha in {
        ('macos','aarch64','torch'):'39fc3532d97897d295ef2ecceedbde12197523d9d3450b52568edcfe7b7be1e3',
        ('linux','aarch64','torch'):'09a74ae6c6e4c51c8098332b19f1747741cde8af5297c395103133ff8cb2fc43',
        ('macos','aarch64','mlx'):'5124c9024470d0f5afd8039e8c012ca3cbf289179184a1317b7081c133cc7446',
    }.items():assert digest(cores[key])==sha
    core=cores['linux','x86_64','torch'];assert core['core_version']=='2.9.0'
    assert set(core['libraries'])=={'lib/'+name for name in('libtorch_cpu.so','libtorch.so','libc10.so','libtorch_global_deps.so','libshm.so','libgomp.so.1')}
    assert core['libraries']['lib/libtorch_cpu.so']==dict(bytes=432273704,sha256='c0d2a2a5a6f3006d88ecbcbdb5573dd3179455abb770cb89a56500f3315deaa1')
    assert not any('python'in name or'cuda'in name for name in core['libraries'])

def test_sdk_sources_pin_actual_cpu_wheels_and_license_provenance():
    value=json.loads((ROOT/'tools/rust_migration/data/native-sdk-sources.json').read_bytes())
    assert value['format']=='ken-native-sdk-sources/1'
    rows={(r['package'],r['os'],r['arch']):r for r in value['sources']}
    assert len(rows)==len(value['sources'])==6
    for key,sha,size in [
        (('torch','linux','x86_64'),'28f6eb31b08180a5c5e98d5bc14eef6909c9f5a1dbff9632c3e02a8773449349',184388168),
        (('onnxruntime','linux','x86_64'),'905409e9eb2ef87f8226e073f56e71faf731c3e480ebd34952cf953730e4a4ff',18024586),
    ]:
        row=rows[key];assert row['wheel']['sha256']==sha and row['wheel']['bytes']==size
        assert row['wheel']['url'].startswith('https://')and len(row['licenses'])==2
    assert rows['torch','linux','x86_64']['version']=='2.9.0+cpu'

import pytest

@pytest.mark.parametrize('system,machine,target',[
    ('Darwin','arm64',('macos','aarch64')),
    ('Linux','aarch64',('linux','aarch64')),
    ('Linux','x86_64',('linux','x86_64')),
    ('macos','aarch64',('macos','aarch64')),
    ('linux','aarch64',('linux','aarch64')),
    ('linux','x86_64',('linux','x86_64')),
])
def test_actual_host_selects_its_exact_onnx_and_torch_records(system,machine,target):
    from tools.rust_migration.native_platform import native_target
    from tools.rust_migration.context_compare import core_for_platform
    from tools.rust_migration.transformer_cores import transformer_core,transformer_cores
    onnx=json.loads((ROOT/'crates/ken-models/resources/onnx-runtime-libraries.json').read_bytes())
    registry=json.loads((ROOT/'tools/rust_migration/data/transformer-cores.json').read_bytes())
    assert native_target(system,machine)==target
    core=core_for_platform(onnx,system,machine);assert(core['os'],core['arch'])==target
    torch=transformer_core(registry,system,machine,'torch');assert(torch['os'],torch['arch'])==target
    assert all((r['os'],r['arch'])==target for r in transformer_cores(registry,system,machine))

@pytest.mark.parametrize('system,machine',[('Darwin','x86_64'),('Linux','AMD64'),('Windows','AMD64'),('Linux','arm64')])
def test_unregistered_host_has_no_same_os_or_architecture_alias(system,machine):
    from tools.rust_migration.native_platform import native_target
    with pytest.raises(ValueError,match='platform'):native_target(system,machine)

@pytest.mark.parametrize('change',['arm-only','duplicate','missing-backend','format'])
def test_mixed_linux_core_lookup_rejects_ambiguous_or_missing_target(change):
    from tools.rust_migration.transformer_cores import transformer_core
    registry=json.loads((ROOT/'tools/rust_migration/data/transformer-cores.json').read_bytes())
    x86=next(row for row in registry['cores']if row['arch']=='x86_64')
    if change=='arm-only':registry['cores'].remove(x86)
    elif change=='duplicate':registry['cores'].append(dict(x86))
    elif change=='missing-backend':x86['backend']='mlx'
    else:registry['format']='unversioned'
    with pytest.raises(ValueError):transformer_core(registry,'Linux','x86_64','torch')

def test_x86_onnx_lookup_rejects_duplicate_or_foreign_records():
    from tools.rust_migration.context_compare import core_for_platform
    registry=json.loads((ROOT/'crates/ken-models/resources/onnx-runtime-libraries.json').read_bytes())
    x86=core_for_platform(registry,'Linux','x86_64')
    for rows in ([row for row in registry['libraries']if row is not x86],registry['libraries']+[dict(x86)]):
        with pytest.raises(ValueError,match='platform'):core_for_platform(dict(registry,libraries=rows),'Linux','x86_64')

def test_old_os_only_transformer_profiles_cannot_be_used_as_x86_originals(tmp_path,monkeypatch):
    from tools.rust_migration import transformer_execution as execution
    from tools.rust_migration.transformer_evidence import source_identity
    monkeypatch.setattr(execution.platform,'system',lambda:'Linux')
    monkeypatch.setattr(execution.platform,'machine',lambda:'x86_64')
    prepared=tmp_path/'prepared.json';prepared.write_text(json.dumps(dict(format='ken-transformer-preparation/1',platform='linux',architecture='x86_64',source_files=source_identity(ROOT))))
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='x86_64.*original'):
        execution.execute_platform(ROOT,prepared,tmp_path/'missing-legacy',tmp_path/'sources',out)
    assert not out.exists()
