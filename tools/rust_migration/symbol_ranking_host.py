"""Source-bound complete symbol composition over controlled leaves and native Ettin."""
from pathlib import Path
import gzip,json,math,os,shutil
from .native_json import NativeJsonCapture,identity,load,same_value,verify_native_json
from .native_core_evidence import require
from .native_binary import check_native_architecture
from .python_witnesses_host import verify_host as verify_operations,grammar_bytes
from .symbol_ranking_reference import FIXTURE,validate_reference
from .ettin_host import generated_files,REGISTRATION,RUNTIME
from .ettin_reference import source_state
from .ettin_compare import _score_errors,TOLERANCES
from .context_compare import core_for_platform
from .command_gates import run_command_gates,command_gate_errors,run_python_scope,python_scope_errors
PREFIX='ken-symbol-ranking-'
REFERENCE_ID={'bytes': 45331, 'sha256': '15a7cd909a553a9d17e51f632fec693a1a85bbe61704efcf850c06e2bf6237b8'}
TEST_FILES=['tests/rust_migration/test_symbol_ranking_reference.py','tests/rust_migration/test_symbol_ranking_host.py']
PYTHON_ROOTS=25
COMMANDS={'symbol-build':['cargo','build','--locked','--offline','-p','ken-retrieval','--example','symbol_ranking_probe']}
def reference(repo):
    require(identity(repo/FIXTURE)==REFERENCE_ID,'preserved symbol ranking original differs')
    value=json.loads(gzip.decompress((repo/FIXTURE).read_bytes()));require(not validate_reference(value),'original symbol ranking contract differs');return value

def request(repo,original,root):
    definition=load(repo/REGISTRATION)
    return dict(grammar_manifest=str(root/'grammar-manifest'),registration=definition,source=str(root/'source'/definition['source']['revision']),cache=str(root/'prepared'),runtime_registration=load(repo/RUNTIME),library=str(root/'runtime-core'),cases=[{key:row[key]for key in('id','input')}for row in original['cases']])

def compare(original,actual,core):
    errors=[]
    try:
        require(set(actual)=={'format','runtime','cases'}and actual['format']=='ken-symbol-ranking-native/1','native symbol ranking format differs')
        require(same_value(actual['runtime'],core),'actual symbol runtime differs')
        require([r['id']for r in actual['cases']]==[r['id']for r in original['cases']],'native cases differ')
        for frame,row in zip(original['cases'],actual['cases'],strict=True):
            require(set(row)=={'id','observations'},'foreign native row fields');wanted=frame['observations'];observed=row['observations']
            require(isinstance(observed,list)and len(observed)==2,'cold/warm observations required')
            if frame['input']['model']['kind']=='controlled':
                require(same_value(wanted,observed),frame['id']+': controlled composition differs');continue
            for a,b in zip(wanted,observed,strict=True):
                require(set(a)==set(b)and same_value(a['calls'],b['calls'])and same_value(a['cache'],b['cache']),frame['id']+': source/cache/calls differ')
                x,y=a['result'],b['result'];require(set(x)==set(y),'ranking fields differ')
                for key in('order','code_view_used','witnesses'):require(same_value(x[key],y[key]),frame['id']+': '+key+' differs')
                errors.extend(_score_errors(dict(scores=a['first_scores'],details=a['first_inference']),dict(scores=b['first_scores'],details=b['first_inference']),a['calls'][0],frame['id']+'.first'))
                for key in('code_scores','mean_scores'):
                    require(isinstance(y[key],list)and len(x[key])==len(y[key]),'candidate score count differs')
                    for u,v in zip(x[key],y[key],strict=True):
                        require(type(v)in(int,float)and math.isfinite(v)and not(u==0 and v!=0)and abs(u-v)<=TOLERANCES['atol']+TOLERANCES['rtol']*abs(u),'candidate '+key+' differs')
                # Additional inference has one value per deduplicated admitted view.
                # Its score vector is validated separately above; use its own real
                # call/document cardinality for the shared metadata validator.
                score_call=next(c for c in reversed(a['calls'])if c['op']=='score');count=len(score_call['texts'])
                errors.extend(_score_errors(dict(scores=[0.]*count,details=x['additional_inference']),dict(scores=[0.]*count,details=y['additional_inference']),score_call,frame['id']+'.additional'))
        return errors
    except(OSError,ValueError,KeyError,TypeError,IndexError,StopIteration)as error:return errors+[str(error)]

def verify_capture(packet,repo):
    try:
        require(not (errors:=verify_operations(packet,repo)),'complete operations parent: '+str(errors));original=reference(repo);out=packet/'symbol-ranking';capture=out/'native';host=load(packet/'HOST.json')
        require((host['os'],host['arch'])==('linux','x86_64'),'symbol ranking requires Linux x86_64')
        require(identity(out/'ORIGINAL.json.gz')==REFERENCE_ID,'original transport differs')
        require((out/'grammar-manifest').read_bytes()==grammar_bytes(repo),'symbol grammar differs')
        require(not (errors:=verify_native_json(capture,PREFIX,generated_files=generated_files(original))),str(errors))
        execution=load(capture/'execution.json');root=Path(execution['cwd']);require(root.is_absolute()and not root.is_relative_to(repo.resolve())and'..'not in root.parts,'symbol ranker ran inside checkout')
        require((execution['system'],execution['machine'])==('linux','x86_64'),'symbol execution host differs')
        binary=out/'bin/symbol_ranking_probe';check_native_architecture(binary,('linux','x86_64'));wanted=request(repo,original,root)
        require(same_value(load(capture/'inputs.json'),wanted),'symbol request contains answers or foreign inputs')
        core=core_for_platform(wanted['runtime_registration'],'Linux','x86_64');resources={'native-probe':identity(binary),'runtime-core':{k:core[k]for k in('bytes','sha256')},'grammar-manifest':identity(out/'grammar-manifest')}
        resources.update({'source/'+wanted['registration']['source']['revision']+'/'+name:row for name,row in original['definition']['source']['artifacts'].items()})
        require(execution['native_sha256']==identity(binary)['sha256']and same_value(execution['owned_before'],resources),'symbol native resources differ')
        require(not (errors:=compare(original,load(capture/'stdout.json'),core)),str(errors));return[]
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def verify_host(packet,repo):
    try:
        require(not (errors:=verify_capture(packet,repo)),str(errors));out=packet/'symbol-ranking'
        return command_gate_errors(out/'gates',COMMANDS,record_name='RUST.json')or python_scope_errors(out,TEST_FILES,PYTHON_ROOTS)
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]

def run_host(repo,packet):
    original=reference(repo);out=packet/'symbol-ranking';out.mkdir();(out/'gates').mkdir();environment=os.environ.copy()
    try:
        os.environ['CARGO_TARGET_DIR']=str(repo/'target');run_command_gates(out/'gates',COMMANDS,record_name='RUST.json')
        binary=repo/'target/debug/examples/symbol_ranking_probe';(out/'bin').mkdir();shutil.copyfile(binary,out/'bin/symbol_ranking_probe');shutil.copyfile(repo/FIXTURE,out/'ORIGINAL.json.gz');(out/'grammar-manifest').write_bytes(grammar_bytes(repo))
        definition=load(repo/REGISTRATION);source=Path(os.environ['KEN_ETTIN_SOURCE']);require(source_state(source,definition['source'])==definition['source']['artifacts'],'symbol source differs')
        library=Path(load(packet/'SDK.json')['prepared']['onnx_library']);os.environ['KEN_ORT_LIBRARY']=str(library)
        with NativeJsonCapture(binary,out/'native',repo=repo,prefix=PREFIX,generated_files=generated_files(original))as capture:
            inputs=request(repo,original,capture.root);shutil.copyfile(out/'grammar-manifest',inputs['grammar_manifest']);shutil.copyfile(library,inputs['library'])
            for name in definition['source']['artifacts']:
                target=Path(inputs['source'])/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/name,target)
            capture.run(inputs)
        require(not (errors:=verify_capture(packet,repo)),str(errors));os.environ['KEN_SYMBOL_RANKING_PACKET']=str(packet);run_python_scope(out,TEST_FILES)
        require(not (errors:=verify_host(packet,repo)),str(errors))
    finally:os.environ.clear();os.environ.update(environment)
