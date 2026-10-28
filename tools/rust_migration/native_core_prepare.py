"""Publish authenticated CPU SDK data without importing a Python model runtime."""
from __future__ import annotations
from pathlib import Path,PurePosixPath
import hashlib,json,os,platform,shutil,subprocess,sys,tempfile
from urllib.request import urlopen
from .context_compare import core_for_platform
from .native_binary import check_native_architecture
from .native_json import identity,load
from .native_platform import native_target
from .transformer_cores import transformer_core
from .transformer_prepare import copy_torch_sdk

def _verified(path:Path,record:dict,label:str):
    if(type(record.get('bytes'))is not int or record['bytes']<=0 or not isinstance(record.get('sha256'),str)
       or len(record['sha256'])!=64 or not path.is_file()or path.is_symlink()or path.stat().st_size!=record['bytes']):
        raise ValueError(label+' bytes differ')
    with path.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=record['sha256']:raise ValueError(label+' hash differs')

def verified_archive(source:dict,cache:Path)->Path:
    wheel=source;name=wheel['filename']
    if not isinstance(name,str)or Path(name).name!=name or name in('.','..'):raise ValueError('unsafe native SDK source name')
    path=cache/name
    if not path.exists()and not path.is_symlink():
        if not wheel['url'].startswith('https://'):raise ValueError('HTTPS native SDK source required')
        cache.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=cache,prefix='.sdk-download-',delete=False)as stream:
            temporary=Path(stream.name);size=0
            with urlopen(wheel['url'],timeout=120)as response:
                while chunk:=response.read(min(1024*1024,wheel['bytes']+1-size)):
                    stream.write(chunk);size+=len(chunk)
                    if size>wheel['bytes']:raise ValueError('oversized native SDK source')
        _verified(temporary,wheel,'native SDK source')
        os.link(temporary,path);temporary.unlink()
    _verified(path,wheel,'native SDK source')
    return path

def _archive(row:dict,cache:Path)->Path:
    return verified_archive(row['wheel'],cache)

def _relative(value:str)->Path:
    path=PurePosixPath(value)
    if not value or path.is_absolute()or'..'in path.parts or str(path)!=value:raise ValueError('unsafe native SDK member')
    return Path(value)

def prepare_native_cores(repo:Path,cache:Path,out:Path,*,target:tuple[str,str])->dict:
    if any(not p.is_absolute()for p in(repo,cache,out)):raise ValueError('explicit absolute native SDK paths required')
    if out.exists()or out.is_symlink():raise ValueError('fresh native SDK destination required')
    target=native_target(*target)
    if target!=native_target(platform.system(),platform.machine()):raise ValueError('native SDK target differs from actual host')
    sources=load(repo/'tools/rust_migration/data/native-sdk-sources.json')
    if sources['format']!='ken-native-sdk-sources/1':raise ValueError('versioned native SDK sources required')
    selected=[]
    for package in('onnxruntime','torch'):
        rows=[row for row in sources['sources']if(row['package'],row['os'],row['arch'])==(package,*target)]
        if len(rows)!=1:raise ValueError('ambiguous or missing native SDK source')
        selected.append(rows[0])
    archives=[_archive(row,cache)for row in selected]
    onnx=core_for_platform(load(repo/'crates/ken-models/resources/onnx-runtime-libraries.json'),*target)
    torch=transformer_core(load(repo/'tools/rust_migration/data/transformer-cores.json'),*target,'torch')
    uv=shutil.which('uv')
    if not uv:raise ValueError('prepare the explicit uv development tool')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-sdk-data-',dir=out.parent)as extraction,tempfile.TemporaryDirectory(prefix='.native-sdk-ready-',dir=out.parent)as publication:
        data=Path(extraction);stage=Path(publication)/'ready';stage.mkdir()
        command=[uv,'pip','install','--python',sys.executable,'--target',str(data),'--no-deps','--no-index',*[str(p)for p in archives]]
        result=subprocess.run(command,capture_output=True,check=False)
        (stage/'source-install.stdout.log').write_bytes(result.stdout);(stage/'source-install.stderr.log').write_bytes(result.stderr)
        if result.returncode:raise ValueError('native SDK data extraction failed: '+result.stderr.decode(errors='replace'))
        filename='libonnxruntime.1.25.1.dylib'if target[0]=='macos'else'libonnxruntime.so.1.25.1'
        source=data/'onnxruntime/capi'/filename;_verified(source,onnx,'ONNX core');check_native_architecture(source,target)
        (stage/'onnx').mkdir();shutil.copyfile(source,stage/'onnx'/filename)
        for name,record in torch['libraries'].items():
            relative=_relative(name);source=data/'torch'/relative
            if not source.is_file():source=data/'torch.libs'/relative.name
            _verified(source,record,'Torch core');check_native_architecture(source,target)
        copy_torch_sdk(data/'torch',stage/'torch-sdk',torch)
        licenses={}
        for row in selected:
            destination=stage/'licenses'/row['package'];destination.mkdir(parents=True)
            for record in row['licenses']:
                source=data/_relative(record['member']);_verified(source,record,'native SDK license')
                target_license=destination/source.name
                if target_license.exists():raise ValueError('duplicate native SDK license name')
                shutil.copyfile(source,target_license);licenses[str(target_license.relative_to(stage))]=identity(target_license)
        report=dict(format='ken-native-cpu-cores/1',os=target[0],arch=target[1],sources=selected,onnx_runtime=onnx,torch_runtime=torch,licenses=licenses,
                    prepared=dict(onnx_library=str(out/'onnx'/filename),torch_core=str(out/'torch-sdk')),
                    extraction=dict(command=command,exit=result.returncode,python_runtime_imported=False),NativeCPUCore_x86_64_accepted=False,M2_accepted=False,migration_complete=False)
        (stage/'PREPARATION.json').write_text(json.dumps(report,indent=2)+'\n')
        if out.exists()or out.is_symlink():raise ValueError('native SDK destination already exists')
        stage.rename(out)
    return report
