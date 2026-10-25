"""Produce native runtime records and immutable source snapshots, without acceptance."""
from pathlib import Path
import json,platform,shutil,subprocess,tarfile
from .native_json import NativeJsonCapture,identity,load
from .native_platform import native_target
from .native_binary import check_native_architecture
from .native_core_evidence import PREFIX,core_request,core_source_identity,runtime_records,resource_names,verify_core_capture

VALIDATION_FILES=('.github/workflows/rust-runtime-cores.yml','pyproject.toml','uv.lock','tools/rust_migration/data/native-sdk-sources.json','tools/rust_migration/data/transformer-cores.json')
SUPPORT_FILES=('docs/superpowers/specs/2026-10-24-rust-x86-runtime-cores-design.md','docs/superpowers/plans/2026-10-24-rust-x86-runtime-cores.md')
def tooling_identity(repo:Path):
    paths=[path for folder in('tools/rust_migration','tests/rust_migration')for path in(repo/folder).glob('*.py')]
    paths.extend(repo/name for name in VALIDATION_FILES)
    return{str(path.relative_to(repo)):identity(path)for path in sorted(paths)}

def capture_packet(repo:Path,module:Path,sdk:Path,out:Path):
    if(out/'HOST.json').exists():raise ValueError('native core packet already captured')
    target=native_target(platform.system(),platform.machine());ready=load(sdk/'PREPARATION.json')
    if(ready['os'],ready['arch'])!=target:raise ValueError('prepared SDK host differs')
    sources=core_source_identity(repo);binary=repo/'target/debug/examples/native_core_probe'
    check_native_architecture(binary,target);check_native_architecture(module,target)
    out.mkdir(parents=True,exist_ok=True);(out/'bin').mkdir();shutil.copy2(binary,out/'bin/native_core_probe');shutil.copy2(module,out/'bin/backend')
    module_id=identity(module);(out/'MODULE.json').write_text(json.dumps(module_id,indent=2)+'\n');shutil.copyfile(sdk/'PREPARATION.json',out/'SDK.json')
    with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX)as capture:
        onnx_registration,onnx,torch=runtime_records(repo,target);library,backend=resource_names(target)
        (capture.root/'onnx').mkdir();shutil.copyfile(ready['prepared']['onnx_library'],capture.root/'onnx'/library)
        for name in torch['libraries']:
            path=capture.root/'torch'/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(ready['prepared']['torch_core'])/name,path)
        shutil.copyfile(module,capture.root/backend)
        capture.run(core_request(repo,capture.root,module_id,target))
    if sources!=core_source_identity(repo):raise ValueError('native core sources changed during execution')
    (out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n')
    host=dict(format='ken-native-cpu-core-host/1',system=platform.system(),machine=platform.machine(),os=target[0],arch=target[1],python=platform.python_version(),rustc=subprocess.check_output(['rustc','--version'],text=True).strip(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip())
    (out/'HOST.json').write_text(json.dumps(host,indent=2)+'\n')
    errors=verify_core_capture(out,repo)
    if errors:raise ValueError(errors)

def snapshot_packet(repo:Path,out:Path):
    sources=core_source_identity(repo)
    if sources!=load(out/'SOURCES.json'):raise ValueError('native core source changed after capture')
    tooling=tooling_identity(repo);records={**sources,**tooling,**{name:identity(repo/name)for name in SUPPORT_FILES}}
    with tarfile.open(out/'source-snapshot.tar.gz','w:gz')as archive:
        for name in sorted(records):archive.add(repo/name,arcname=name,recursive=False)
    (out/'SNAPSHOT.json').write_text(json.dumps(records,indent=2)+'\n');(out/'VALIDATION-SOURCES.json').write_text(json.dumps(tooling,indent=2)+'\n')
