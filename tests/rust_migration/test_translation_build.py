"""Build proof follows Cargo's selected CT2 output, never an arbitrary old cache."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.rust_migration.preparation import PreparedTranslationBuild
from tools.rust_migration.translation_build import build_proof, prepare_openblas, proof_errors


def selected_build(tmp_path):
    cmake=tmp_path/'cmake';cmake.write_text('#!/bin/sh\nprintf "cmake version 3.31.10\\n"\n');cmake.chmod(0o755)
    out=tmp_path/'target/release/build/ct2rs-selected/out';cache=out/'build/CMakeCache.txt';cache.parent.mkdir(parents=True)
    cache.write_text(f'CMAKE_BUILD_TYPE:STRING=Release\nWITH_RUY:BOOL=ON\nWITH_ACCELERATE:BOOL=ON\nWITH_OPENBLAS:BOOL=OFF\nOPENMP_RUNTIME:STRING=NONE\nCMAKE_COMMAND:INTERNAL={cmake}\nCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG\n')
    compiler=out/'build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake';compiler.parent.mkdir(parents=True)
    compiler.write_text('set(CMAKE_CXX_COMPILER_ID "AppleClang")\nset(CMAKE_CXX_COMPILER_VERSION "17.0.0")\n')
    log=tmp_path/'release.log'
    row={'reason':'build-script-executed','package_id':'registry+https://github.com/rust-lang/crates.io-index#ct2rs@0.10.1','out_dir':str(out)}
    log.write_text('Building native dependencies\n'+json.dumps(row)+'\n')
    return log,cache,PreparedTranslationBuild(cmake),row


def test_selected_release_core_proof_records_cmake_compiler_and_platform_backends(tmp_path):
    log,_,build,_=selected_build(tmp_path)
    actual=build_proof(tmp_path,log,build,system='Darwin',architecture='arm64')
    assert proof_errors(actual,'Darwin','arm64')==[]
    assert actual['cmake']['version']=='3.31.10'
    assert actual['core']['build_type']=='Release'
    assert actual['core']['float_backend']=='Accelerate'
    assert actual['core']['compiler']=={'id':'AppleClang','version':'17.0.0'}
    assert actual['openblas'] is None
    for field,value in [('build_type','Debug'),('float_backend','Ruy'),('int8_backend','unknown'),('openmp_runtime','COMP')]:
        bad=deepcopy(actual);bad['core'][field]=value
        assert proof_errors(bad,'Darwin','arm64'),field
    bad=deepcopy(actual);bad['cmake']['version']='4.0.0'
    assert proof_errors(bad,'Darwin','arm64')
    assert proof_errors(actual,'Linux','aarch64')


def test_stale_unselected_cache_cannot_replace_cargos_actual_build_proof(tmp_path):
    log,cache,build,row=selected_build(tmp_path)
    stale=tmp_path/'target/release/build/ct2rs-stale/out/build/CMakeCache.txt';stale.parent.mkdir(parents=True)
    stale.write_text('CMAKE_BUILD_TYPE:STRING=Debug\n')
    assert build_proof(tmp_path,log,build,system='Darwin',architecture='arm64')['core']['build_type']=='Release'
    for text in ['',json.dumps(row|{'package_id':'registry+index#ct2rs@0.10.0'}),
                 json.dumps(row)+'\n'+json.dumps(row|{'out_dir':str(stale.parent.parent)}),
                 json.dumps(row|{'out_dir':str(tmp_path/'outside')})]:
        log.write_text(text)
        with pytest.raises(ValueError):build_proof(tmp_path,log,build,system='Darwin',architecture='arm64')
    log.write_text(json.dumps(row))
    for key in ['CMAKE_BUILD_TYPE:STRING=Release','WITH_RUY:BOOL=ON','WITH_ACCELERATE:BOOL=ON']:
        original=cache.read_text();cache.write_text(original.replace(key,key.split('=')[0]+'=OFF'))
        with pytest.raises(ValueError):build_proof(tmp_path,log,build,system='Darwin',architecture='arm64')
        cache.write_text(original)


def test_missing_wrong_or_replaced_cmake_fails_instead_of_reusing_cached_native_output(tmp_path):
    log,_,build,_=selected_build(tmp_path)
    for path in [tmp_path/'missing',Path('relative')]:
        with pytest.raises(ValueError):build_proof(tmp_path,log,PreparedTranslationBuild(path),system='Darwin',architecture='arm64')
    for body in ['printf "cmake version 4.0.0\\n"','exit 0']:
        build.cmake.write_text('#!/bin/sh\n'+body+'\n')
        with pytest.raises(ValueError):build_proof(tmp_path,log,build,system='Darwin',architecture='arm64')


def test_unverified_openblas_archive_fails_before_building_or_creating_destination(tmp_path):
    archive=tmp_path/'OpenBLAS.tar.gz';archive.write_bytes(b'changed source')
    destination=tmp_path/'prepared'
    for path in [archive,tmp_path/'missing']:
        with pytest.raises(ValueError,match='OpenBLAS source'):prepare_openblas(path,destination)
        assert not destination.exists()
