from pathlib import Path
import json,os,shutil
import pytest
ROOT=Path(__file__).resolve().parents[2]
def test_missing_preference_capture_rejects_summary(tmp_path):
    from tools.rust_migration.symbol_preferences_host import verify_capture
    (tmp_path/'summary.json').write_text('{"passed":true}');assert verify_capture(tmp_path,ROOT)
@pytest.fixture
def packet(tmp_path):
    source=Path(os.environ.get('KEN_SYMBOL_PREFERENCES_PACKET',ROOT/'.ken/rust-migration/symbol-preferences/packet'))
    out=tmp_path/'packet';shutil.copytree(source,out);return out
def test_actual_preference_capture_is_input_only_and_native(packet):
    from tools.rust_migration.symbol_preferences_host import verify_capture
    assert not verify_capture(packet,ROOT)
@pytest.mark.parametrize('change',['input-answer','requirement','order','catalog','binary','owned','original','parent'])
def test_resealed_preference_capture_rejects(packet,change):
    from tools.rust_migration.symbol_preferences_host import verify_capture
    from tools.rust_migration.native_json import identity
    assert not verify_capture(packet,ROOT)
    out=packet/'symbol-preferences';capture=out/'native';execution=capture/'execution.json';record=json.loads(execution.read_bytes())
    if change=='input-answer':
        path=capture/'inputs.json';value=json.loads(path.read_bytes());value['expected']={};path.write_text(json.dumps(value));record['request_sha256']=identity(path)['sha256']
    elif change in('requirement','order','catalog'):
        path=capture/'stdout.json';value=json.loads(path.read_bytes())
        if change=='requirement':value['cases'][0]['result']['operations']=['invented']
        elif change=='order':next(r for r in value['cases']if 'order'in r['result'])['result']['order']=[999]
        else:value['catalogs'][0][0]['test_case']=not value['catalogs'][0][0]['test_case']
        path.write_text(json.dumps(value));record['stdout_sha256']=identity(path)['sha256']
    elif change=='binary':(out/'bin/symbol_preferences_probe').write_bytes(b'changed')
    elif change=='owned':record['owned_before']['native-probe']['bytes']+=1;record['owned_after']['native-probe']['bytes']+=1
    elif change=='original':(out/'ORIGINAL.json.gz').write_bytes(b'changed')
    else:(packet/'SDK.json').unlink()
    execution.write_text(json.dumps(record));assert verify_capture(packet,ROOT)
