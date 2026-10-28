"""The native module build binds actual SDK inputs and source bytes."""
from pathlib import Path
import os
import json
import pytest

ROOT=Path(__file__).resolve().parents[2]

def test_missing_sdk_is_rejected_before_compilation_or_publication(tmp_path):
    from tools.rust_migration.translation_cpu_build import build
    with pytest.raises(ValueError,match='SDK'):
        build(ROOT,tmp_path/'missing',tmp_path/'out',cmake=tmp_path/'missing-cmake')
    assert not(tmp_path/'out').exists()

def test_actual_module_build_authenticates_sources_sdk_and_binary(tmp_path):
    from tools.rust_migration.translation_cpu_build import build,verify_build
    from tools.rust_migration.native_json import identity
    sdk=Path(os.environ['KEN_CT2_SDK']);out=tmp_path/'backend'
    report=build(ROOT,sdk,out,cmake=Path(os.environ['CMAKE']))
    assert not verify_build(out,ROOT,sdk)
    assert report['registration']['runtimes'][0]['module']==identity(Path(report['module_path']))
    assert report['registration']['runtimes'][0]['abi']==1
    assert report['core_root']==str(sdk/'lib')
    (out/'build/libken_ct2_backend.so').write_bytes(b'changed native module')
    assert verify_build(out,ROOT,sdk)

@pytest.fixture(scope='module')
def actual_build(tmp_path_factory):
    from tools.rust_migration.translation_cpu_build import build
    sdk=Path(os.environ['KEN_CT2_SDK']);out=tmp_path_factory.mktemp('ct2-build-proof')/'backend'
    build(ROOT,sdk,out,cmake=Path(os.environ['CMAKE']))
    return sdk,out

@pytest.mark.parametrize('change',['sdk','flags','compiler','link-core','rpath','commands','format','cmake-version','cmake-bytes'])
def test_resealed_contradictory_build_proof_is_rejected(actual_build,change):
    from tools.rust_migration.translation_cpu_build import verify_build,PROOF_FILES
    from tools.rust_migration.native_json import identity
    sdk,out=actual_build
    assert not verify_build(out,ROOT,sdk)
    originals={name:(out/name).read_bytes()for name in(*PROOF_FILES,'PREPARATION.json')}
    try:
        report=json.loads(originals['PREPARATION.json']);member=None
        if change in('sdk','flags'):
            member='build/CMakeCache.txt';text=(out/member).read_text()
            text=text.replace('KEN_CT2_SDK:UNINITIALIZED='+str(sdk),'KEN_CT2_SDK:UNINITIALIZED=/foreign/sdk')if change=='sdk'else text.replace('CMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG','CMAKE_CXX_FLAGS_RELEASE:STRING=-O0 -ffast-math')
            (out/member).write_text(text)
        elif change=='compiler':
            member='build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake'
            (out/member).write_text((out/member).read_text().replace('set(CMAKE_CXX_COMPILER_ID "GNU")','set(CMAKE_CXX_COMPILER_ID "Foreign")').replace('set(CMAKE_CXX_COMPILER_ID "Clang")','set(CMAKE_CXX_COMPILER_ID "Foreign")'))
        elif change in('link-core','rpath'):
            member='build/CMakeFiles/ken_ct2_backend.dir/link.txt';text=(out/member).read_text()
            text=text.replace(str(sdk/'lib/libctranslate2-fd146744.so.4.8.2'),'/foreign/libcore.so')if change=='link-core'else text.replace('$ORIGIN','/foreign')
            (out/member).write_text(text)
        elif change=='commands':
            member='commands.json';commands=json.loads((out/member).read_bytes());commands[0].append('-DCMAKE_CXX_FLAGS=-ffast-math')
            (out/member).write_text(json.dumps(commands));report['commands']=commands
        elif change=='format':report['format']='unregistered-build'
        elif change=='cmake-version':report['cmake_version']='cmake version 0.0.0\n'
        else:report['cmake_identity']['sha256']='0'*64
        if member:
            assert(out/member).read_bytes()!=originals[member],change
            report['proof_files'][member]=identity(out/member)
        (out/'PREPARATION.json').write_text(json.dumps(report))
        assert verify_build(out,ROOT,sdk),change
    finally:
        for name,raw in originals.items():(out/name).write_bytes(raw)
