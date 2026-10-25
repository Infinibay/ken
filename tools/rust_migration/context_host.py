"""Run contextual histories against their own host's preserved original."""
from pathlib import Path
import json,os,shutil,sys,tarfile
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_platform import native_target
from .native_binary import check_native_architecture
from .native_core_evidence import verify_core_packet,require
from .context_compare import select_oracle,core_for_platform,compare_output,RUNTIME_REGISTRATION
from .context_reference import context_cases,TOLERANCES,snapshot_state
from .command_gates import run_command_gates,command_gate_errors
from .integration_validate import rust_gate_errors
from .receipts import junit_states

PREFIX='ken-context-host-'
LEGACY='docs/validation/rust-migration-2026-10-18/m2-context/reference.json'
X86='crates/ken-models/tests/fixtures/context/linux-x86_64-original.json'
LEGACY_SHA='343fd57f5f644beff252260784fca165d2edf0ab8f38319815f2b0357b181af6'
X86_SHA='b1feb05a1abe09637450f55c6988f669884183df76f675e6696a7827ee0a5733'
REGISTRATION='src/ken/embedder/data/code-context-int8.json'
SUPPORT=(REGISTRATION,LEGACY,'docs/superpowers/specs/2026-10-24-rust-x86-context-design.md','docs/superpowers/plans/2026-10-24-rust-x86-context.md')
TEST_FILE='tests/rust_migration/test_x86_context_evidence.py'
RUST_TEST=['cargo','test','--locked','--offline','-p','ken-models','--test','context_encoder']
COMMANDS={'context-list':[*RUST_TEST,'--','--list'],'context-tests':[*RUST_TEST,'--no-fail-fast'],'context-build':['cargo','build','--locked','--offline','-p','ken-models','--example','context_probe']}

def host_original(repo:Path,system:str,machine:str):
    target=native_target(system,machine)
    system,machine=('Darwin','arm64')if target[0]=='macos'else('Linux',target[1])
    path=repo/(X86 if target==('linux','x86_64')else LEGACY)
    require(identity(path)['sha256']==(X86_SHA if target==('linux','x86_64')else LEGACY_SHA),'preserved contextual original bytes differ')
    document=load(path)
    if target==('linux','x86_64'):document={'platforms':{'Linux/x86_64':document}}
    original=select_oracle(document,system,machine)
    require(original['cases']==context_cases()and original['tolerances']==TOLERANCES,'fixed contextual cases/tolerances changed')
    require(original['definition']==load(repo/REGISTRATION),'contextual registration differs')
    return original,path

def context_request(repo:Path,original:dict,root:Path):
    return dict(registration=original['definition'],snapshot=str(root/'model'/original['definition']['revision']),runtime_registration=load(repo/RUNTIME_REGISTRATION.relative_to(Path(__file__).resolve().parents[2])),library=str(root/'runtime-core'),cases=original['cases'])

def verify_context_support(packet:Path,repo:Path):
    try:
        from .native_snapshot import read_source_snapshot
        expected={name:identity(repo/name)for name in SUPPORT};out=packet/'context'
        require(load(out/'SNAPSHOT.json')==expected,'complete contextual support inventory differs')
        read_source_snapshot(out,required=expected)
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError,EOFError,tarfile.TarError)as error:return[str(error)]

def extract_context_snapshot(packet:Path,destination:Path):
    from .native_core_evidence import extract_core_snapshot
    from .native_snapshot import read_source_snapshot
    extract_core_snapshot(packet,destination)
    records=load(packet/'context/SNAPSHOT.json');require(set(records)==set(SUPPORT),'contextual support members differ')
    payloads=read_source_snapshot(packet/'context',required=records)
    for name,raw in payloads.items():
        path=destination/name
        if path.exists():require(identity(path)==records[name],'crossed parent/contextual support')
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    errors=verify_context_support(packet,destination);require(not errors,str(errors))
    return destination

def verify_context_capture(packet:Path,repo:Path):
    try:
        errors=verify_core_packet(packet,repo);require(not errors,'parent CPU core packet: '+str(errors))
        errors=verify_context_support(packet,repo);require(not errors,str(errors))
        host=load(packet/'HOST.json');target=native_target(host['system'],host['machine']);original,path=host_original(repo,host['system'],host['machine']);out=packet/'context';capture=out/'native'
        require(identity(out/'ORIGINAL.json')==identity(path),'contextual original transport differs')
        errors=verify_native_json(capture,PREFIX,macos_confinement=True);require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd']);require(not root.is_relative_to(repo.resolve()),'contextual process ran in checkout')
        require((execution['system'],execution['machine'])==('macos'if target[0]=='macos'else'linux',host['machine']),'contextual execution host differs')
        binary=out/'bin/context_probe';check_native_architecture(binary,target);binary_id=identity(binary)
        require(execution['native_sha256']==binary_id['sha256'],'contextual executable differs')
        request=context_request(repo,original,root);require(same_value(load(capture/'inputs.json'),request),'contextual request contains answers or foreign inputs')
        core=core_for_platform(request['runtime_registration'],host['system'],host['machine'])
        resources={'native-probe':binary_id,'runtime-core':{key:core[key]for key in('bytes','sha256')}}
        resources.update({'model/'+original['definition']['revision']+'/'+name:row for name,row in original['artifacts'].items()})
        require(execution['owned_before']==resources,'contextual owned resource closure differs')
        errors=compare_output(original,load(capture/'stdout.json'),core);require(not errors,str(errors))
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_context_gates(out:Path):
    try:
        errors=command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json');require(not errors,str(errors))
        listed=(out/'gates/context-list.log').read_text();output=(out/'gates/context-tests.log').read_text()
        import re
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==8,'all8contextual native roots required')
        records=load(out/'gates/PYTHON.json');require(set(records)=={'python-list','python-tests'},'contextual tooling commands missing')
        for name,row in records.items():
            argv=row['command'];require(Path(argv[0]).name in('python','python3','python3.12')and argv[1:-1]==['-m','pytest','-o','addopts=','-q',TEST_FILE],'contextual tooling scope differs')
            require(argv[-1]=='--collect-only'if name=='python-list'else argv[-1].startswith('--junitxml='),'contextual tooling discovery/JUnit missing')
        errors=command_gate_errors(out/'gates',{name:row['command']for name,row in records.items()},record_name='PYTHON.json');require(not errors,str(errors))
        discovered=[line for line in(out/'gates/python-list.log').read_text().splitlines()if line.startswith(TEST_FILE+'::')]
        expected={line.replace(TEST_FILE,TEST_FILE[:-3].replace('/','.'))for line in discovered};states=junit_states(out/'gates/python.xml')
        require(len(discovered)==len(expected)==10 and expected==set(states)and set(states.values())=={'passed'},'all10contextual tooling roots required')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_context_host(packet:Path,repo:Path):
    return verify_context_capture(packet,repo)or verify_context_gates(packet/'context')

def run_context_host(repo:Path,sdk:Path,snapshot:Path,packet:Path):
    host=load(packet/'HOST.json');original,path=host_original(repo,host['system'],host['machine']);ready=load(sdk/'PREPARATION.json')
    require(snapshot_state(snapshot,original['definition'])==original['artifacts'],'prepared context weights differ')
    out=packet/'context';out.mkdir();gates=out/'gates';gates.mkdir();environment=os.environ.copy()
    records={name:identity(repo/name)for name in SUPPORT}
    with tarfile.open(out/'source-snapshot.tar.gz','w:gz')as archive:
        for name in SUPPORT:archive.add(repo/name,arcname=name,recursive=False)
    (out/'SNAPSHOT.json').write_text(json.dumps(records,indent=2)+'\n')
    try:
        os.environ.update(KEN_ORT_LIBRARY=ready['prepared']['onnx_library'],KEN_CONTEXT_SNAPSHOT=str(snapshot),CARGO_TARGET_DIR=str(repo/'target'))
        run_command_gates(gates,COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/context_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/context_probe');shutil.copyfile(path,out/'ORIGINAL.json')
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,macos_confinement=True)as capture:
            request=context_request(repo,original,capture.root)
            for name in original['artifacts']:
                destination=Path(request['snapshot'])/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(snapshot/name,destination)
            shutil.copyfile(Path(ready['prepared']['onnx_library']),Path(request['library']))
            capture.run(request)
        errors=verify_context_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_CONTEXT_HOST_PACKET']=str(packet)
        command=[sys.executable,'-m','pytest','-o','addopts=','-q',TEST_FILE]
        run_command_gates(gates,{'python-list':[*command,'--collect-only'],'python-tests':[*command,'--junitxml='+str(gates/'python.xml')]},record_name='PYTHON.json')
        errors=verify_context_host(packet,repo);require(not errors,str(errors))
    finally:
        os.environ.clear();os.environ.update(environment)
