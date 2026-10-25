"""Authenticate actual CPU core loading independently of passing summaries."""
from pathlib import Path
from .native_json import identity,load,same_value,verify_native_json
from .native_platform import native_target
from .native_binary import check_native_architecture
from .context_compare import core_for_platform
from .transformer_cores import transformer_core
PREFIX='ken-native-cpu-cores-'
CONFINEMENT_PREFIX='ken-native-core-confinement-'

def verify_core_confinement(packet:Path,target):
    if target[0]!='macos':return[]
    try:
        capture=packet/'confinement'
        errors=verify_native_json(capture,CONFINEMENT_PREFIX,macos_confinement=True);require(not errors,str(errors))
        execution=load(capture/'execution.json');binary=packet/'bin/native_isolation_probe';check_native_architecture(binary,target)
        require((execution['system'],execution['machine'])==('macos','arm64'),'confinement witness host differs')
        require(execution['owned_before']=={'native-probe':identity(binary)}and execution['native_sha256']==identity(binary)['sha256'],'confinement witness binary differs')
        require(same_value(load(capture/'inputs.json'),{'format':'ken-native-isolation-request/1'}),'confinement witness request differs')
        require(same_value(load(capture/'stdout.json'),dict(format='ken-native-isolation-observation/1',self_child_blocked=True,absolute_child_blocked=True,network_blocked=True)),'actual process/network enforcement absent')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def require(value,message):
    if not value:raise ValueError(message)

def core_source_identity(repo:Path):
    from .index_validate import source_identity
    sources=source_identity(repo)
    for folder in('native/ken-torch-backend','native/ken-mlx-backend'):
        for path in sorted((repo/folder).rglob('*')):
            if path.is_file()and not any(part in('target','.ken','__pycache__')for part in path.relative_to(repo/folder).parts):
                sources[str(path.relative_to(repo))]=identity(path)
    return sources

def runtime_records(repo:Path,target):
    onnx_registration=load(repo/'crates/ken-models/resources/onnx-runtime-libraries.json')
    onnx=core_for_platform(onnx_registration,*target)
    torch=transformer_core(load(repo/'tools/rust_migration/data/transformer-cores.json'),*target,'torch')
    return onnx_registration,onnx,torch

def resource_names(target):
    return('libonnxruntime.1.25.1.dylib','backend.dylib')if target[0]=='macos'else('libonnxruntime.so.1.25.1','backend.so')

def core_request(repo:Path,root:Path,module:dict,target):
    registration,onnx,torch=runtime_records(repo,target);library,backend=resource_names(target)
    declaration=dict(format='ken-native-transformer/1',backend='torch',runtimes=[dict(os=target[0],arch=target[1],core_version=torch['core_version'],module=module,libraries=torch['libraries'])])
    return dict(format='ken-native-cpu-core-request/1',onnx=dict(registration=registration,library=str(root/'onnx'/library)),torch=dict(registration=declaration,module=str(root/backend),core_root=str(root/'torch')))

def verify_core_capture(packet:Path,repo:Path):
    try:
        errors=verify_native_json(packet/'native',PREFIX,macos_confinement=True);require(not errors,str(errors))
        execution=load(packet/'native/execution.json');root=Path(execution['cwd'])
        require(execution['system']in('linux','macos'),'unknown native core host')
        target=native_target('Darwin'if execution['system']=='macos'else'Linux',execution['machine'])
        errors=verify_core_confinement(packet,target);require(not errors,str(errors))
        require(not root.is_relative_to(repo.resolve()),'native core process ran inside checkout')
        require(load(packet/'SOURCES.json')==core_source_identity(repo),'native core source snapshot differs')
        binary=packet/'bin/native_core_probe';module=packet/'bin/backend';binary_id=identity(binary);module_id=identity(module)
        check_native_architecture(binary,target);check_native_architecture(module,target)
        require(module_id==load(packet/'MODULE.json')and binary_id['sha256']==execution['native_sha256'],'native core binary/module differs')
        request=core_request(repo,root,module_id,target)
        require(same_value(load(packet/'native/inputs.json'),request),'native core input contains answers or foreign resources')
        registration,onnx,torch=runtime_records(repo,target);library,backend=resource_names(target)
        resources={'native-probe':binary_id,backend:module_id,'onnx/'+library:{key:onnx[key]for key in('bytes','sha256')}}
        resources.update({'torch/'+name:record for name,record in torch['libraries'].items()})
        require(execution['owned_before']==resources,'unexpected or stale native core resource closure')
        expected=dict(format='ken-native-cpu-core-observation/1',os=target[0],arch=target[1],onnx=onnx,torch=dict(backend='torch',os=target[0],arch=target[1],declared_core_version=torch['core_version'],module=module_id,libraries=torch['libraries']))
        require(same_value(load(packet/'native/stdout.json'),expected),'actual loaded core identity differs')
        loader=(packet/'native/stderr.log').read_text()
        require('libtorch_cpu.'in loader and 'ken-transformer-'in loader,'actual private Torch core loading absent')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_core_snapshot(packet:Path,repo:Path):
    import tarfile
    try:
        from .native_core_packet import tooling_identity,SUPPORT_FILES
        from .native_snapshot import read_source_snapshot
        sources=core_source_identity(repo);tooling=tooling_identity(repo)
        require(load(packet/'SOURCES.json')==sources,'complete native core sources differ')
        require(load(packet/'VALIDATION-SOURCES.json')==tooling,'complete native core tooling differs')
        expected={**sources,**tooling,**{name:identity(repo/name)for name in SUPPORT_FILES}}
        require(load(packet/'SNAPSHOT.json')==expected,'complete native core snapshot differs')
        read_source_snapshot(packet,required=expected)
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError,tarfile.TarError)as error:return[str(error)]

def extract_core_snapshot(packet:Path,destination:Path):
    from .native_snapshot import extract_source_snapshot
    required={**load(packet/'SOURCES.json'),**load(packet/'VALIDATION-SOURCES.json')}
    extract_source_snapshot(packet,destination,required=required)
    errors=verify_core_snapshot(packet,destination)
    if errors:raise ValueError(errors)
    return destination

def verify_core_review(path:Path,sources:dict,tooling:dict):
    try:
        record=load(path)
        require(record['format']=='ken-native-cpu-core-review/1'and record['whole_plan']is True and record['critical_open']==[]and record['important_open']==[],'whole-plan native core review remains open')
        require(isinstance(record['reviewer'],str)and bool(record['reviewer']),'native core reviewer missing')
        require(record['accepted_sources']==sources and record['accepted_tooling']==tooling,'native core review does not bind sources/tooling')
        raw=Path(record['raw_review']['path']);require(not raw.is_absolute()and'..'not in raw.parts and identity(path.parent/raw)==record['raw_review']['identity'],'raw native core review differs')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_core_packet(packet:Path,repo:Path):
    try:
        from .native_core_gates import verify_core_gates
        host=load(packet/'HOST.json');target=native_target(host['system'],host['machine'])
        require(host['format']=='ken-native-cpu-core-host/1'and(host['os'],host['arch'])==target,'native core host differs')
        require(host['python']=='3.12.9'and host['rustc'].startswith('rustc 1.95.0 '),'pinned native core tools differ')
        require(len(host['commit'])==40 and all(ch in'0123456789abcdef'for ch in host['commit']),'native core candidate commit missing')
        execution=load(packet/'native/execution.json');require((execution['system'],execution['machine'])==('macos'if target[0]=='macos'else'linux',host['machine']),'recorded and actual core hosts differ')
        sdk=load(packet/'SDK.json');registration,onnx,torch=runtime_records(repo,target)
        require((sdk['os'],sdk['arch'])==target and sdk['onnx_runtime']==onnx and sdk['torch_runtime']==torch,'prepared runtime registration differs')
        sources=load(repo/'tools/rust_migration/data/native-sdk-sources.json')['sources']
        expected=[next(row for row in sources if(row['package'],row['os'],row['arch'])==(name,*target))for name in('onnxruntime','torch')]
        require(sdk['sources']==expected and sdk['extraction']['exit']==0,'prepared SDK source proof differs')
        require(all(sdk[key]is False for key in('NativeCPUCore_x86_64_accepted','M2_accepted','migration_complete')),'SDK preparation cannot claim acceptance')
        return verify_core_capture(packet,repo)or verify_core_gates(packet/'gates',system=target[0])or verify_core_snapshot(packet,repo)
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration)as error:return[str(error)]

CORE_HOSTS={'linux-x86_64':('linux','x86_64'),'linux-aarch64':('linux','aarch64'),'macos-arm64':('macos','aarch64')}
def aggregate_core_hosts(directory:Path,repo:Path,review:Path|None=None):
    result=dict(format='ken-native-cpu-core-matrix/1',gates_passed=False,NativeCPUCore_x86_64_accepted=False,M2_x86_64_accepted=False,M3_x86_64_accepted=False,M4_accepted=False,migration_complete=False,platforms=[],errors=[])
    try:
        for name,target in CORE_HOSTS.items():
            packet=directory/name;errors=verify_core_packet(packet,repo);require(not errors,name+': '+str(errors))
            host=load(packet/'HOST.json');require((host['os'],host['arch'])==target,'native core matrix host missing')
            result['platforms'].append(dict(platform=name,commit=host['commit'],sources=load(packet/'SOURCES.json'),tooling=load(packet/'VALIDATION-SOURCES.json'),native=identity(packet/'bin/native_core_probe'),module=identity(packet/'bin/backend')))
        rows=result['platforms'];require(all(row['commit']==rows[0]['commit']and row['sources']==rows[0]['sources']and row['tooling']==rows[0]['tooling']for row in rows),'native core hosts used different sources/tooling')
        result['gates_passed']=True
        if review is not None:
            errors=verify_core_review(review,rows[0]['sources'],rows[0]['tooling']);require(not errors,str(errors));result['NativeCPUCore_x86_64_accepted']=True
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:result['errors'].append(str(error))
    return result
