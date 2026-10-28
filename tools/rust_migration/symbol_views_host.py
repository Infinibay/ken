"""Native symbol views compose the accepted x86 Ettin runtime without oracle replay."""
from pathlib import Path
import gzip,json,math,os,re,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .context_compare import core_for_platform
from .ettin_host import verify_ettin_host,generated_files,REGISTRATION,RUNTIME
from .ettin_reference import source_state
from .symbol_views_reference import FIXTURE,validate_reference
from .command_gates import run_command_gates,command_gate_errors,run_lint_gates,lint_gate_errors,run_python_scope,python_scope_errors
from .integration_validate import rust_gate_errors

PREFIX='ken-symbol-views-'
REFERENCE_ID=dict(bytes=7320,sha256='80bf3b93cfa93533da9c3fdf0b9654e0317c7785b00fe059e7b2b5b51f59261f')
TEST_FILES=['tests/rust_migration/test_command_gates.py','tests/rust_migration/test_symbol_views_reference.py','tests/rust_migration/test_symbol_views_host.py']
PYTHON_ROOTS=27
NATIVE_TEST=['cargo','test','--locked','--offline','-p','ken-core','-p','ken-retrieval','--all-targets']
COMMANDS={'native-list':[*NATIVE_TEST,'--','--list'],'native-tests':[*NATIVE_TEST,'--no-fail-fast'],'probe-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','symbol_views_probe']}
LINT={'fmt':['cargo','fmt','--all','--check'],'clippy':['cargo','clippy','--locked','--offline','-p','ken-core','-p','ken-retrieval','--all-targets','--','-D','warnings']}

def reference(repo:Path):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved symbol-view original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));errors=validate_reference(value);require(not errors,str(errors));return value

def request(repo:Path,original:dict,root:Path):
    registration=load(repo/REGISTRATION)
    return dict(registration=registration,source=str(root/'source'/registration['source']['revision']),cache=str(root/'prepared'),runtime_registration=load(repo/RUNTIME),library=str(root/'runtime-core'),frames=[frame['input']for frame in original['frames']])

def compare_frames(original:dict,actual:dict,core:dict):
    from .ettin_compare import _score_errors
    errors=[]
    if set(actual)!={'format','runtime','results'}or actual['format']!='ken-symbol-views-native/1'or not same_value(actual['runtime'],core):return['native symbol view runtime differs']
    rows=actual['results']
    if not isinstance(rows,list)or [r.get('id')for r in rows]!=[f['input']['id']for f in original['frames']]:return['native symbol view frames differ']
    for frame,row in zip(original['frames'],rows,strict=True):
        wanted=frame['result'];got=row['result'];name=frame['input']['id']
        if set(row)!={'id','result','calls'}or set(got)!=set(wanted):errors.append(name+': symbol result fields differ');continue
        for key in('views','order','code_view_used'):
            if not same_value(got[key],wanted[key]):errors.append(name+': '+key+' differs')
        if not same_value(row['calls'],frame['calls']):errors.append(name+': native pair/score calls differ')
        errors.extend(_score_errors(dict(scores=wanted['original_scores'],details=wanted['first_inference']),dict(scores=got['original_scores'],details=got['first_inference']),dict(texts=frame['input']['card_texts']),name+'.first'))
        for key in('code_scores','mean_scores'):
            a,b=wanted[key],got[key]
            if not isinstance(b,list)or len(a)!=len(b):errors.append(name+': '+key+' count differs');continue
            for x,y in zip(a,b,strict=True):
                if type(y)not in(int,float)or not math.isfinite(y)or abs(x-y)>1e-5+1e-5*abs(x)or(x==0 and y!=0):errors.append(name+': '+key+' differs')
        a,b=wanted['additional_inference'],got['additional_inference']
        if not isinstance(b,dict)or set(a)!=set(b):errors.append(name+': extra inference details differ');continue
        for key,x in a.items():
            y=b[key]
            if key in('token_ms','inference_ms'):
                if type(y)not in(int,float)or not math.isfinite(y)or y<0 or(x==0 and y!=0):errors.append(name+': invalid timing')
            elif not same_value(x,y):errors.append(name+': inference '+key+' differs')
    return errors

def verify_capture(packet:Path,repo:Path):
    try:
        errors=verify_ettin_host(packet,repo);require(not errors,'accepted Ettin parent: '+str(errors))
        original=reference(repo);out=packet/'symbol-views';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'symbol view scope requires Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'symbol-view original transport differs')
        errors=verify_native_json(capture,PREFIX,generated_files=generated_files(original));require(not errors,str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd']);require(not root.is_relative_to(repo.resolve())and'..'not in root.parts,'symbol views ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'symbol view native host differs')
        binary=out/'bin/symbol_views_probe';check_native_architecture(binary,('linux','x86_64'));binary_id=identity(binary)
        require(execution['native_sha256']==binary_id['sha256'],'symbol view binary differs')
        wanted=request(repo,original,root);require(same_value(load(capture/'inputs.json'),wanted),'symbol request contains answers or foreign inputs')
        core=core_for_platform(wanted['runtime_registration'],'Linux','x86_64');resources={'native-probe':binary_id,'runtime-core':{k:core[k]for k in('bytes','sha256')}}
        resources.update({'source/'+wanted['registration']['source']['revision']+'/'+name:row for name,row in original['source_artifacts'].items()})
        require(same_value(execution['owned_before'],resources),'symbol view immutable resources differ')
        errors=compare_frames(original,load(capture/'stdout.json'),core);require(not errors,str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as e:return[str(e)]

def verify_host(packet:Path,repo:Path):
    try:
        errors=verify_capture(packet,repo);require(not errors,str(errors));out=packet/'symbol-views'
        errors=command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json');require(not errors,str(errors))
        listed=(out/'gates/native-list.log').read_text();output=(out/'gates/native-tests.log').read_text()
        require(not rust_gate_errors(listed,output)and len(re.findall(r'^([^\n]+): test$',listed,re.M))==149,'all149native retrieval/core roots required')
        return lint_gate_errors(out/'gates',LINT)or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as e:return[str(e)]

def run_host(repo:Path,sdk:Path,source:Path,packet:Path):
    original=reference(repo);registration=load(repo/REGISTRATION);ready=load(sdk/'PREPARATION.json')
    require(source_state(source,registration['source'])==original['source_artifacts'],'prepared symbol view source differs')
    out=packet/'symbol-views';out.mkdir();gates=out/'gates';gates.mkdir();environment=os.environ.copy()
    try:
        os.environ.update(KEN_ORT_LIBRARY=ready['prepared']['onnx_library'],KEN_ETTIN_SOURCE=str(source),CARGO_TARGET_DIR=str(repo/'target'))
        run_command_gates(gates,COMMANDS,record_name='RUST.json');run_lint_gates(gates,LINT)
        binary=repo/'target/debug/examples/symbol_views_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/symbol_views_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz')
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,generated_files=generated_files(original))as capture:
            inputs=request(repo,original,capture.root)
            for name in original['source_artifacts']:
                destination=Path(inputs['source'])/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,destination)
            shutil.copyfile(ready['prepared']['onnx_library'],inputs['library']);capture.run(inputs)
        errors=verify_capture(packet,repo);require(not errors,str(errors))
        os.environ['KEN_SYMBOL_VIEWS_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        errors=verify_host(packet,repo);require(not errors,str(errors))
    finally:os.environ.clear();os.environ.update(environment)
