"""Native CT2 SDK publication authenticates every source and owned member."""
from pathlib import Path
import hashlib,io,json,struct,tarfile,zipfile
import pytest

REGISTRY='tools/rust_migration/data/translation-cpu-core.json'

def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

@pytest.fixture
def sources(tmp_path):
    root=tmp_path/'repo';cache=tmp_path/'archives';cache.mkdir()
    actual=Path(__file__).resolve().parents[2]
    registration=json.loads((actual/REGISTRY).read_bytes())
    runtime=json.loads((actual/registration['runtime_registration']).read_bytes())
    registration['libraries']=runtime['runtimes'][0]['libraries']
    libraries={}
    for name in registration['libraries']:
        raw=bytearray(32);raw[:6]=b'\x7fELF\x02\x01';raw[18:20]=struct.pack('<H',62)
        libraries[name]=bytes(raw)+name.encode()
    wheel=cache/'core.whl'
    with zipfile.ZipFile(wheel,'w')as stream:
        for name,raw in libraries.items():stream.writestr('ctranslate2.libs/'+name,raw)
    header_members={'include/ctranslate2/translator.h':('source/include/translator.h',b'public translator header'),
                    'include/ken-ct2/backend.h':('source/src/backend.h',b'backend declaration'),
                    'licenses/CTranslate2-LICENSE':('source/LICENSE',b'retained license')}
    headers=cache/'headers.crate'
    with tarfile.open(headers,'w:gz')as stream:
        for member,raw in header_members.values():
            entry=tarfile.TarInfo(member);entry.size=len(raw);stream.addfile(entry,io.BytesIO(raw))
    registration['wheel']=dict(filename=wheel.name,url='https://unused.invalid/core.whl',**identity(wheel.read_bytes()))
    registration['headers']=dict(filename=headers.name,url='https://unused.invalid/headers.crate',**identity(headers.read_bytes()))
    registration['libraries']={name:identity(raw)for name,raw in libraries.items()}
    runtime['runtimes'][0]['libraries']=registration['libraries']
    native=root/registration['runtime_registration'];native.parent.mkdir(parents=True);native.write_text(json.dumps(runtime))
    registration['header_files']={path:dict(member=member,**identity(raw))for path,(member,raw)in header_members.items()}
    path=root/REGISTRY;path.parent.mkdir(parents=True);path.write_text(json.dumps(registration))
    return root,cache,registration,libraries

def test_sdk_publication_owns_exact_authenticated_native_libraries_headers_and_licenses(sources,tmp_path):
    from tools.rust_migration.translation_cpu_prepare import prepare,verify_sdk
    root,cache,registration,libraries=sources;out=tmp_path/'sdk'
    result=prepare(root,cache,out)
    assert not verify_sdk(out,root)
    assert result['python_runtime_imported']is False
    assert set(result['files'])=={'lib/'+name for name in libraries}|set(registration['header_files'])
    for name,raw in libraries.items():assert (out/'lib'/name).read_bytes()==raw
    assert (out/'include/ctranslate2/translator.h').read_bytes()==b'public translator header'
    assert (out/'licenses/CTranslate2-LICENSE').read_bytes()==b'retained license'

def test_existing_sdk_is_preserved_before_any_source_download(tmp_path):
    from tools.rust_migration.translation_cpu_prepare import prepare
    out=tmp_path/'sdk';out.mkdir();(out/'keep').write_bytes(b'previous')
    with pytest.raises(ValueError,match='destination'):prepare(tmp_path/'repo',tmp_path/'cache',out)
    assert (out/'keep').read_bytes()==b'previous'and not(tmp_path/'cache').exists()

def test_foreign_platform_does_not_publish_or_download(tmp_path,monkeypatch):
    from tools.rust_migration import translation_cpu_prepare as module
    monkeypatch.setattr(module.platform,'machine',lambda:'aarch64')
    with pytest.raises(ValueError,match='Linux x86'):module.prepare(tmp_path/'repo',tmp_path/'cache',tmp_path/'sdk')
    assert not(tmp_path/'sdk').exists()and not(tmp_path/'cache').exists()

@pytest.mark.parametrize('source',['wheel','headers'])
def test_corrupt_archives_are_preserved_and_never_published(source,sources,tmp_path):
    from tools.rust_migration.translation_cpu_prepare import prepare
    root,cache,registration,_=sources;path=cache/registration[source]['filename'];path.write_bytes(b'changed source')
    with pytest.raises(ValueError,match='source'):prepare(root,cache,tmp_path/'sdk')
    assert path.read_bytes()==b'changed source'and not(tmp_path/'sdk').exists()

@pytest.mark.parametrize('change',['core','header','extra','manifest'])
def test_resealed_or_extra_sdk_members_cannot_change_registered_inputs(change,sources,tmp_path):
    from tools.rust_migration.translation_cpu_prepare import prepare,verify_sdk
    root,cache,_,libraries=sources;out=tmp_path/'sdk';prepare(root,cache,out)
    manifest=out/'PREPARATION.json';record=json.loads(manifest.read_bytes())
    name='lib/'+next(iter(libraries))if change=='core'else'include/ctranslate2/translator.h'
    if change=='extra':(out/'foreign').write_bytes(b'extra')
    elif change=='manifest':record['source_wheel']['sha256']='0'*64
    else:
        (out/name).write_bytes(b'changed');record['files'][name]=identity(b'changed')
    manifest.write_text(json.dumps(record));assert verify_sdk(out,root)
