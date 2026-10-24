"""Native SDK preparation authenticates bytes before publishing anything."""
from pathlib import Path
import hashlib,io,tarfile
import pytest,subprocess,shutil
from tools.rust_migration.grammar_prepare import prepare_grammars,native_platform


def fixture(tmp_path,*,bad_digest=False,duplicate=False):
    payload=b'authenticated C grammar fixture'
    source=io.BytesIO()
    with tarfile.open(fileobj=source,mode='w')as archive:
        for name in (['libs/libtree_sitter_cpp.so','other/libtree_sitter_cpp.so']if duplicate else['libs/libtree_sitter_cpp.so']):
            info=tarfile.TarInfo(name);info.size=len(payload);archive.addfile(info,io.BytesIO(payload))
    compressed=subprocess.run([shutil.which('zstd'),'-q','-c'],input=source.getvalue(),capture_output=True,check=True).stdout
    platform=native_platform();cache=tmp_path/'cache';cache.mkdir();archive=cache/f'parsers-{platform}.tar.zst';archive.write_bytes(compressed)
    library=dict(file='libtree_sitter_cpp.so',bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),
        revision='a'*40,license=dict(id='MIT',text='MIT fixture license\n'))
    lock=dict(format='ken-grammar-lock/1',pack=dict(version='1.8.1',revision='b'*40,bundles={platform:dict(
        url='https://example.invalid/'+archive.name,bytes=len(compressed),sha256='0'*64 if bad_digest else hashlib.sha256(compressed).hexdigest(),libraries={'cpp':library})}))
    return lock,cache,payload


def test_authenticated_bundle_publishes_native_bytes_and_license_then_reuses_cache(tmp_path):
    lock,cache,payload=fixture(tmp_path);out=tmp_path/'sdk'
    first=prepare_grammars(lock,cache,out)
    assert (out/'libtree_sitter_cpp.so').read_bytes()==payload
    assert (out/'licenses/cpp.txt').read_text()=='MIT fixture license\n'
    (cache/f'parsers-{native_platform()}.tar.zst').unlink()
    assert prepare_grammars(lock,cache,out)==first


def test_wrong_bundle_identity_never_publishes_output(tmp_path):
    lock,cache,_=fixture(tmp_path,bad_digest=True);out=tmp_path/'sdk'
    with pytest.raises(ValueError,match='bundle identity'):prepare_grammars(lock,cache,out)
    assert not out.exists()


def test_corrupt_prepared_module_is_rejected_without_overwriting_it(tmp_path):
    lock,cache,_=fixture(tmp_path);out=tmp_path/'sdk';prepare_grammars(lock,cache,out)
    changed=out/'libtree_sitter_cpp.so';changed.write_bytes(b'changed')
    with pytest.raises(ValueError,match='prepared grammar'):prepare_grammars(lock,cache,out)
    assert changed.read_bytes()==b'changed'


def test_duplicate_archive_module_is_ambiguous_and_cannot_publish(tmp_path):
    lock,cache,_=fixture(tmp_path,duplicate=True);out=tmp_path/'sdk'
    with pytest.raises(ValueError,match='ambiguous grammar'):prepare_grammars(lock,cache,out)
    assert not out.exists()


def test_unsafe_output_name_is_rejected_before_archive_use(tmp_path):
    lock,cache,_=fixture(tmp_path);lock['pack']['bundles'][native_platform()]['libraries']['cpp']['file']='../escape.so'
    with pytest.raises(ValueError,match='grammar filename'):prepare_grammars(lock,cache,tmp_path/'sdk')
    assert not (tmp_path/'escape.so').exists()

def test_registered_grammar_bundle_preserves_arm_and_pins_linux_x86_64():
    import json
    root=Path(__file__).resolve().parents[2]
    lock=json.loads((root/'crates/ken-syntax/grammars.lock.json').read_bytes())
    bundles=lock['pack']['bundles']
    assert 'linux-x86_64'in bundles,'Linux x86_64 grammar registration is missing'
    assert lock['pack']['version']=='1.8.1'and lock['pack']['revision']=='33602ce7d17edd24cc00a1a9fe7129a61138f8ef'
    for host,digest in {'macos-arm64':'1a5ef6f0f3c705bb65e15dda7d5a541e353c6be8b5932b70092b837b97fb6670','linux-aarch64':'d8f79fc4221b8d0e017a2faed80dcbd4b0836b44833cbe406469bb9e858e32da'}.items():
        assert hashlib.sha256(json.dumps(bundles[host],sort_keys=True,separators=(',',':')).encode()).hexdigest()==digest
    bundle=bundles['linux-x86_64']
    assert bundle['bytes']==19144528 and bundle['sha256']=='f670f0582aa186df8da69d60624653df3d482f85546e162bdfaedbc77d2cf390'
    assert bundle['url']=='https://github.com/xberg-io/tree-sitter-language-pack/releases/download/v1.8.1/parsers-linux-x86_64.tar.zst'
    rows=bundle['libraries'];assert len(rows)==13 and len({row['file']for row in rows.values()})==13
    for language,row in rows.items():
        arm=bundles['linux-aarch64']['libraries'][language]
        assert all(row[field]==arm[field]for field in ('file','revision','repository','symbol','license'))
        assert row['bytes']>0 and len(row['sha256'])==64


def test_another_host_prepared_sdk_cannot_be_overwritten_or_reused(tmp_path):
    import json
    lock,cache,payload=fixture(tmp_path);out=tmp_path/'sdk'
    first=prepare_grammars(lock,cache,out)
    first['platform']='linux-foreign'
    (out/'manifest.json').write_text(json.dumps(first))
    before={str(p.relative_to(out)):p.read_bytes()for p in out.rglob('*')if p.is_file()}
    with pytest.raises(ValueError,match='prepared grammar manifest differs'):prepare_grammars(lock,cache,out)
    assert before=={str(p.relative_to(out)):p.read_bytes()for p in out.rglob('*')if p.is_file()}
