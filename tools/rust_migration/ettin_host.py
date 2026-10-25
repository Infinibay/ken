"""Execute the preserved Linux x86_64 Ettin profile without recapturing Python."""
from pathlib import Path
import json,os,re,shutil,sys
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_platform import native_target
from .native_binary import check_native_architecture
from .native_core_evidence import verify_core_packet,require
from .context_compare import core_for_platform
from .ettin_compare import compare_output
from .ettin_reference import ettin_cases,TOLERANCES,source_state
from .command_gates import run_command_gates,command_gate_errors
from .integration_validate import rust_gate_errors
from .receipts import junit_states

PREFIX='ken-ettin-host-'
ORIGINAL='crates/ken-models/tests/fixtures/ettin/linux-x86_64-original.json'
ORIGINAL_SHA='ec1a7477107da440828fd0f46ab2c6d9be45a5d64c7c516306797aa2636e20ce'
REGISTRATION='crates/ken-models/resources/ettin-68m-fp32.json'
RUNTIME='crates/ken-models/resources/onnx-runtime-libraries.json'
TEST_FILES=['tests/rust_migration/test_native_json_outputs.py','tests/rust_migration/test_x86_ettin_host.py']
PYTHON_ROOTS=38
RUST_TEST=['cargo','test','--locked','--offline','-p','ken-models','--test','onnx_reranker']
COMMANDS={'ettin-list':[*RUST_TEST,'--','--list'],'ettin-tests':[*RUST_TEST,'--no-fail-fast'],'ettin-build':['cargo','build','--locked','--offline','-p','ken-models','--example','ettin_probe']}

def python_commands(executable:str,out:Path):
    command=[executable,'-m','pytest','-o','addopts=','-q',*TEST_FILES]
    return{'python-list':[*command,'--collect-only'],'python-tests':[*command,'--junitxml='+str(out/'gates/python.xml')]}

def host_original(repo:Path,system:str,machine:str):
    require(native_target(system,machine)==('linux','x86_64'),'Ettin host scope requires Linux x86_64')
    path=repo/ORIGINAL
    require(identity(path)==dict(bytes=667940,sha256=ORIGINAL_SHA),'preserved Ettin original bytes differ')
    original=load(path)
    require((original['platform'],original['architecture'])==('Linux','x86_64'),'crossed Ettin original host')
    require(original['definition']==load(repo/REGISTRATION),'registered Ettin definition differs')
    require(original['cases']==ettin_cases()and original['tolerances']==TOLERANCES,'fixed Ettin histories/tolerances differ')
    return original,path

def generated_files(original:dict):
    return{'prepared/'+name:record for name,record in original['artifacts'].items()}

def ettin_request(repo:Path,original:dict,root:Path):
    return dict(registration=load(repo/REGISTRATION),source=str(root/'source'/original['definition']['source']['revision']),cache=str(root/'prepared'),runtime_registration=load(repo/RUNTIME),library=str(root/'runtime-core'),cases=original['cases'])

def verify_ettin_capture(packet:Path,repo:Path):
    try:
        host=load(packet/'HOST.json');original,path=host_original(repo,host['system'],host['machine'])
        errors=verify_core_packet(packet,repo);require(not errors,'parent CPU core packet: '+str(errors))
        out=packet/'ettin';capture=out/'native'
        require(identity(out/'ORIGINAL.json')==identity(path),'Ettin original transport differs')
        errors=verify_native_json(capture,PREFIX,generated_files=generated_files(original));require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd'])
        require((execution['system'],execution['machine'])==('linux','x86_64'),'actual Ettin execution host differs')
        require('..'not in root.parts and not root.is_relative_to(repo.resolve()),'Ettin process ran in checkout')
        binary=out/'bin/ettin_probe';check_native_architecture(binary,('linux','x86_64'));binary_id=identity(binary)
        require(execution['native_sha256']==binary_id['sha256'],'Ettin executable differs')
        request=ettin_request(repo,original,root)
        require(same_value(load(capture/'inputs.json'),request),'Ettin request contains answers or foreign inputs')
        core=core_for_platform(request['runtime_registration'],'Linux','x86_64')
        resources={'native-probe':binary_id,'runtime-core':{key:core[key]for key in('bytes','sha256')}}
        revision=original['definition']['source']['revision']
        resources.update({'source/'+revision+'/'+name:row for name,row in original['source_artifacts'].items()})
        require(same_value(execution['owned_before'],resources),'Ettin immutable resource closure differs')
        errors=compare_output(original,load(capture/'stdout.json'),core);require(not errors,str(errors))
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_ettin_gates(out:Path):
    try:
        errors=command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json');require(not errors,str(errors))
        listed=(out/'gates/ettin-list.log').read_text();output=(out/'gates/ettin-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==16,'all16Ettin native roots required')
        records=load(out/'gates/PYTHON.json');require(set(records)=={'python-list','python-tests'},'Ettin tooling commands missing')
        locations=load(out/'PYTHON-OUTPUT.json')
        require(set(locations)=={'format','recorded_directory'}and locations['format']=='ken-ettin-python-output/1','Ettin recorded output missing')
        recorded=Path(locations['recorded_directory']);require(recorded.is_absolute()and recorded.name=='ettin','Ettin recorded directory differs')
        executable=records['python-list']['command'][0]
        require(Path(executable).name in('python','python3','python3.12'),'Ettin Python executable differs')
        commands=python_commands(executable,recorded)
        for name,row in records.items():require(row['command']==commands[name],'Ettin tooling scope/JUnit destination differs')
        errors=command_gate_errors(out/'gates',commands,record_name='PYTHON.json');require(not errors,str(errors))
        discovered=[]
        for line in(out/'gates/python-list.log').read_text().splitlines():
            for name in TEST_FILES:
                if line.startswith(name+'::'):discovered.append(line.replace(name,name[:-3].replace('/','.')))
        states=junit_states(out/'gates/python.xml')
        require(len(discovered)==len(set(discovered))==PYTHON_ROOTS and set(discovered)==set(states)and set(states.values())=={'passed'},'complete Ettin tooling roots required')
        return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_ettin_host(packet:Path,repo:Path):
    return verify_ettin_capture(packet,repo)or verify_ettin_gates(packet/'ettin')

def run_ettin_host(repo:Path,sdk:Path,source:Path,packet:Path):
    host=load(packet/'HOST.json');original,path=host_original(repo,host['system'],host['machine']);ready=load(sdk/'PREPARATION.json')
    errors=verify_core_packet(packet,repo);require(not errors,str(errors))
    require(source_state(source,original['definition']['source'])==original['source_artifacts'],'prepared Ettin source differs')
    out=packet/'ettin';out.mkdir();gates=out/'gates';gates.mkdir();environment=os.environ.copy()
    try:
        os.environ.update(KEN_ORT_LIBRARY=ready['prepared']['onnx_library'],KEN_ETTIN_SOURCE=str(source),CARGO_TARGET_DIR=str(repo/'target'))
        run_command_gates(gates,COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/ettin_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/ettin_probe');shutil.copyfile(path,out/'ORIGINAL.json')
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,generated_files=generated_files(original))as capture:
            request=ettin_request(repo,original,capture.root)
            for name in original['source_artifacts']:
                destination=Path(request['source'])/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,destination)
            shutil.copyfile(Path(ready['prepared']['onnx_library']),Path(request['library']))
            capture.run(request)
        require(source_state(source,original['definition']['source'])==original['source_artifacts'],'Ettin source changed during execution')
        errors=verify_ettin_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_ETTIN_HOST_PACKET']=str(packet)
        (out/'PYTHON-OUTPUT.json').write_text(json.dumps(dict(format='ken-ettin-python-output/1',recorded_directory=str(out.resolve())),indent=2)+'\n')
        run_command_gates(gates,python_commands(sys.executable,out.resolve()),record_name='PYTHON.json')
        errors=verify_ettin_host(packet,repo);require(not errors,str(errors))
    finally:
        os.environ.clear();os.environ.update(environment)
