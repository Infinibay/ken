"""Prepare pinned Linux BLAS privately and attest Cargo's selected native core."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time

from .compare import _differences
from .preparation import PreparedTranslationBuild

OPENBLAS_SOURCE={'bytes':24404912,'sha256':'4e6e4f5cb14c209262e33e6816d70221a2fe49eb69eaf0a06f065598ac602c68'}
OPENBLAS_OPTIONS=['TARGET=ARMV8','NO_SHARED=1','BUILD_SINGLE=1','NO_LAPACK=1',
                  'ONLY_CBLAS=1','USE_OPENMP=1','NUM_THREADS=64','NUM_PARALLEL=1']
OPENBLAS_FILES={'source.tar.gz','lib/libopenblas.a','include/cblas.h',
                'include/openblas_config.h','lib/pkgconfig/openblas.pc'}


def _record(path:Path)->dict:
    return {'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def _hash(value:object)->bool:
    return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)


def _record_errors(value:object)->bool:
    return (not isinstance(value,dict) or set(value)!={'bytes','sha256'}
        or type(value['bytes']) is not int or value['bytes']<=0 or not _hash(value['sha256']))


def _openblas_errors(value:object)->list[str]:
    if not isinstance(value,dict):return ['prepared OpenBLAS build record required']
    errors=[]
    if set(value)!={'format','platform','architecture','version','source','options','compiler','artifacts','build_ns','build_log_sha256'}:
        return ['complete OpenBLAS provenance required']
    for key,want in [('format','ken-openblas-build/1'),('platform','Linux'),('architecture','aarch64'),
                     ('version','0.3.26'),('source',OPENBLAS_SOURCE),('options',OPENBLAS_OPTIONS)]:
        errors.extend(_differences(want,value[key],'openblas.'+key))
    compiler=value['compiler']
    if (not isinstance(compiler,dict) or set(compiler)!={'path','version'} or not isinstance(compiler['path'],str)
            or not Path(compiler['path']).is_absolute() or not isinstance(compiler['version'],str) or not compiler['version']):
        errors.append('OpenBLAS compiler provenance required')
    records=value['artifacts']
    if not isinstance(records,dict) or set(records)!=OPENBLAS_FILES or any(_record_errors(r) for r in records.values()):
        errors.append('complete OpenBLAS archive/header/pkg-config identities required')
    elif records['source.tar.gz']!=OPENBLAS_SOURCE:errors.append('unregistered OpenBLAS source archive')
    if type(value['build_ns']) is not int or value['build_ns']<=0 or not _hash(value['build_log_sha256']):
        errors.append('actual OpenBLAS build measurement/log identity required')
    return errors


def inspect_openblas(prefix:Path)->dict:
    try:
        if not prefix.is_absolute():raise ValueError('absolute prepared OpenBLAS prefix required')
        receipt=json.loads((prefix/'ken-build.json').read_text())
        errors=_openblas_errors(receipt)
        if errors:raise ValueError('; '.join(errors))
        for name,record in receipt['artifacts'].items():
            if _record(prefix/name)!=record:raise ValueError('prepared OpenBLAS artifact changed: '+name)
        return receipt
    except (OSError,TypeError,KeyError) as error:raise ValueError(f'incomplete prepared OpenBLAS: {error}') from error


def _openblas_snapshot(archive:Path)->bytes:
    """Own bounded, authenticated bytes before executing any build tool."""
    try:
        with os.fdopen(os.open(archive,os.O_RDONLY|os.O_NONBLOCK),'rb') as source:
            metadata=os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=OPENBLAS_SOURCE['bytes']:
                raise ValueError('OpenBLAS source must be a regular archive of the registered size')
            snapshot=source.read(OPENBLAS_SOURCE['bytes']+1)
    except OSError as error:raise ValueError(f'OpenBLAS source unavailable: {error}') from error
    if {'bytes':len(snapshot),'sha256':hashlib.sha256(snapshot).hexdigest()}!=OPENBLAS_SOURCE:
        raise ValueError('OpenBLAS source byte identity mismatch')
    return snapshot


def prepare_openblas(archive:Path,destination:Path)->dict:
    snapshot=_openblas_snapshot(archive)
    if (platform.system(),platform.machine())!=('Linux','aarch64'):
        raise ValueError('OpenBLAS preparation requires registered Linux aarch64')
    if not destination.is_absolute():raise ValueError('absolute private OpenBLAS destination required')
    if destination.exists():return inspect_openblas(destination)
    compiler=shutil.which('cc')
    if not compiler:raise ValueError('native C compiler required for OpenBLAS')
    compiler=str(Path(compiler).resolve())
    version=subprocess.run([compiler,'--version'],text=True,capture_output=True,check=True,timeout=30).stdout
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.openblas-stage-',dir=destination.parent) as temporary:
        stage=Path(temporary);source=stage/'source';source.mkdir();ready=stage/'ready';installed=stage/'installed'
        with tarfile.open(fileobj=io.BytesIO(snapshot)) as package:package.extractall(source,filter='data')
        project=source/'OpenBLAS-0.3.26'
        with tempfile.NamedTemporaryFile(prefix='openblas-attempt-',suffix='.log',dir=destination.parent,delete=False) as log:
            started=time.monotonic_ns()
            completed=subprocess.run(['make','-j2',*OPENBLAS_OPTIONS,'CC='+compiler],cwd=project,
                stdout=log,stderr=subprocess.STDOUT,timeout=1200)
            if completed.returncode==0:
                completed=subprocess.run(['make',*OPENBLAS_OPTIONS,'CC='+compiler,'PREFIX='+str(installed),'install'],
                    cwd=project,stdout=log,stderr=subprocess.STDOUT,timeout=120)
            duration=time.monotonic_ns()-started;log_path=Path(log.name)
        if completed.returncode:raise ValueError(f'OpenBLAS build failed; retained log: {log_path}')
        libraries=list(project.glob('libopenblas_*.a'))
        if len(libraries)!=1:raise ValueError('one actual compiled OpenBLAS archive required')
        for folder in ['lib/pkgconfig','include']:(ready/folder).mkdir(parents=True,exist_ok=True)
        shutil.copyfile(libraries[0],ready/'lib/libopenblas.a')
        for name in ['cblas.h','openblas_config.h']:shutil.copyfile(installed/'include'/name,ready/'include'/name)
        (ready/'source.tar.gz').write_bytes(snapshot)
        (ready/'lib/pkgconfig/openblas.pc').write_text(
            f'prefix={destination}\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\n'
            'Name: OpenBLAS\nDescription: pinned native CPU BLAS\nVersion: 0.3.26\n'
            'Libs: -L${libdir} -lopenblas\nLibs.private: -lm -lgomp\nCflags: -I${includedir}\n')
        receipt={'format':'ken-openblas-build/1','platform':'Linux','architecture':'aarch64','version':'0.3.26',
            'source':OPENBLAS_SOURCE,'options':OPENBLAS_OPTIONS,'compiler':{'path':compiler,'version':version},
            'artifacts':{name:_record(ready/name) for name in sorted(OPENBLAS_FILES)},
            'build_ns':duration,'build_log_sha256':_record(log_path)['sha256']}
        (ready/'ken-build.json').write_text(json.dumps(receipt,indent=2)+'\n')
        inspect_openblas(ready)
        try:ready.rename(destination)
        except OSError:
            if not destination.is_dir():raise
        return inspect_openblas(destination)


def _cmake(path:Path)->dict:
    if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK):
        raise ValueError('explicit absolute executable CMake required')
    process=subprocess.run([str(path),'--version'],text=True,capture_output=True,timeout=30)
    lines=process.stdout.splitlines()
    if process.returncode or process.stderr or not lines or lines[0]!='cmake version 3.31.10':
        raise ValueError('prepared CMake3.31.10 required')
    return {'version':'3.31.10',**_record(path)}


def inspect_prerequisites(prepared:PreparedTranslationBuild,*,system:str|None=None,architecture:str|None=None)->dict:
    system=platform.system() if system is None else system
    architecture=platform.machine() if architecture is None else architecture
    prepared.environment()
    if (system,architecture) not in [('Darwin','arm64'),('Linux','aarch64')]:
        raise ValueError('registered native build platform required')
    cmake=_cmake(prepared.cmake)
    if system=='Linux':
        if prepared.openblas_prefix is None:raise ValueError('explicit prepared Linux OpenBLAS prefix required')
        openblas=inspect_openblas(prepared.openblas_prefix)
    else:
        if prepared.openblas_prefix is not None:raise ValueError('foreign BLAS prefix on macOS')
        openblas=None
    return {'cmake':cmake,'openblas':openblas}


def proof_errors(value:object,system:str,architecture:str)->list[str]:
    try:
        if (system,architecture) not in [('Darwin','arm64'),('Linux','aarch64')]:return ['unregistered translation build platform']
        if not isinstance(value,dict) or set(value)!={'format','platform','architecture','cmake','core','openblas'}:
            return ['complete native translation build proof required']
        errors=_differences({'format':'ken-translation-build/1','platform':system,'architecture':architecture},
            {k:value[k] for k in ['format','platform','architecture']},'native_build')
        cmake=value['cmake']
        if (not isinstance(cmake,dict) or set(cmake)!={'version','bytes','sha256'} or cmake.get('version')!='3.31.10'
                or _record_errors({k:v for k,v in cmake.items() if k!='version'})):
            errors.append('CMake binary/version identity required')
        core=value['core'];wanted={'build_type':'Release','int8_backend':'Ruy',
            'float_backend':'Accelerate' if system=='Darwin' else 'OpenBLAS0.3.26',
            'openmp_runtime':'NONE' if system=='Darwin' else 'COMP','cxx_flags_release':'-O3 -DNDEBUG'}
        if not isinstance(core,dict) or set(core)!=set(wanted)|{'cache_sha256','compiler'}:
            errors.append('selected native core build policy required')
        else:
            errors.extend(_differences(wanted,{k:core[k] for k in wanted},'native_build.core'))
            if not _hash(core['cache_sha256']):errors.append('selected CMake cache identity required')
            compiler=core['compiler']
            if (not isinstance(compiler,dict) or set(compiler)!={'id','version'}
                    or any(not isinstance(v,str) or not v for v in compiler.values())):
                errors.append('actual CMake compiler identity required')
        if system=='Linux':errors.extend(_openblas_errors(value['openblas']))
        elif value['openblas'] is not None:errors.append('macOS requires Accelerate without a foreign BLAS prefix')
        return errors
    except (KeyError,TypeError,ValueError,AttributeError) as error:return [f'malformed native build proof: {error}']


def build_proof(repo:Path,release_log:Path,prepared:PreparedTranslationBuild,*,system:str|None=None,architecture:str|None=None)->dict:
    system=platform.system() if system is None else system
    architecture=platform.machine() if architecture is None else architecture
    inputs=inspect_prerequisites(prepared,system=system,architecture=architecture);selected=set()
    for line in release_log.read_text().splitlines():
        try:row=json.loads(line)
        except ValueError:continue
        if isinstance(row,dict) and row.get('reason')=='build-script-executed' and '#ct2rs@' in row.get('package_id',''):
            if not row['package_id'].endswith('#ct2rs@0.10.1'):raise ValueError('unregistered CTranslate2 build package')
            selected.add(row['out_dir'])
    if len(selected)!=1:raise ValueError('one Cargo-selected native CTranslate2 build output required')
    output=Path(selected.pop()).resolve()
    if not output.is_relative_to((repo/'target/release/build').resolve()):raise ValueError('native build output escaped release target')
    cache=output/'build/CMakeCache.txt';values={}
    for line in cache.read_text().splitlines():
        if ':' in line and '=' in line and not line.startswith(('#','//')):
            key,rest=line.split(':',1);values[key]=rest.split('=',1)[1]
    expected={'CMAKE_BUILD_TYPE':'Release','WITH_RUY':'ON','WITH_ACCELERATE':'ON' if system=='Darwin' else 'OFF',
        'WITH_OPENBLAS':'OFF' if system=='Darwin' else 'ON','OPENMP_RUNTIME':'NONE' if system=='Darwin' else 'COMP'}
    if any(values.get(k)!=v for k,v in expected.items()):raise ValueError('selected CTranslate2 native build policy mismatch')
    if Path(values.get('CMAKE_COMMAND','')).resolve()!=prepared.cmake.resolve():raise ValueError('selected CMake differs from explicit prerequisite')
    compiler_file=output/'build/CMakeFiles/3.31.10/CMakeCXXCompiler.cmake'
    compiler={}
    for key,label in [('CMAKE_CXX_COMPILER_ID','id'),('CMAKE_CXX_COMPILER_VERSION','version')]:
        match=re.search(r'set\('+key+r' "([^"]+)"\)',compiler_file.read_text())
        if not match:raise ValueError('actual CMake compiler identity missing')
        compiler[label]=match.group(1)
    openblas=None
    if system=='Linux':
        prefix=prepared.openblas_prefix
        if prefix is None:raise ValueError('explicit prepared Linux OpenBLAS prefix required')
        openblas=inputs['openblas']
        if (Path(values.get('OPENBLAS_LIBRARY','')).resolve()!=(prefix/'lib/libopenblas.a').resolve()
                or Path(values.get('OPENBLAS_INCLUDE_DIR','')).resolve()!=(prefix/'include').resolve()):
            raise ValueError('selected OpenBLAS archive/headers differ from explicit prerequisite')
    elif prepared.openblas_prefix is not None:raise ValueError('foreign BLAS prefix on macOS')
    result={'format':'ken-translation-build/1','platform':system,'architecture':architecture,'cmake':inputs['cmake'],
        'core':{'build_type':values['CMAKE_BUILD_TYPE'],'int8_backend':'Ruy','float_backend':'Accelerate' if system=='Darwin' else 'OpenBLAS0.3.26',
            'openmp_runtime':values['OPENMP_RUNTIME'],'cxx_flags_release':values.get('CMAKE_CXX_FLAGS_RELEASE'),
            'compiler':compiler,'cache_sha256':_record(cache)['sha256']},'openblas':openblas}
    errors=proof_errors(result,system,architecture)
    if errors:raise ValueError('; '.join(errors))
    return result


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare-openblas'])
    parser.add_argument('--archive',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    result=prepare_openblas(args.archive,args.destination)
    print(json.dumps({'prepared':str(args.destination),'library':result['artifacts']['lib/libopenblas.a']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
